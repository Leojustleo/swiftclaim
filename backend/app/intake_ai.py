import json
import os
import random
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy.orm import Session

from app.models import Case
from app.rag import search_law, search_precedents

LLM_URL = "https://api.deepseek.com/v1/chat/completions"
CHAT_MODEL = "deepseek-chat"

CATEGORIES = [
    "Vattenskada",
    "Brand- eller rökskada",
    "Stormskada",
    "Stöld- eller inbrottsskada",
    "Mögel eller fuktskada",
    "Vitvaruskada",
    "Ansvar bostadsrätt/hyresrätt",
    "Avslaget ärende",
    "Underbetalt ärende",
    "Annan egendomsskada",
]

CATEGORIZE_SYSTEM = (
    "Du är en erfaren svensk skadereglerare på Swiftclaim. Klassificera kundens "
    "skadebeskrivning i exakt en av dessa kategorier:\n"
    + "\n".join(f"- {c}" for c in CATEGORIES)
    + '\n\nSvara endast med JSON: {"category": "<kategori>"}'
)

ASSESS_SYSTEM = (
    "Du är en svensk försäkringsjurist på Swiftclaim. Bedöm kundens ärende mot "
    "lagrum och ARN-praxis nedan. Var saklig och lova aldrig ett utfall.\n\n"
    "Svara endast med JSON:\n"
    "{\n"
    '  "strength": "stark" | "medel" | "svag",\n'
    '  "summary": "<2-4 meningar på svenska, riktade till kunden: vad vi ser i ärendet och varför det är värt att driva>",\n'
    '  "key_arguments": ["<juridiskt argument med lagrumshänvisning>", ...],\n'
    '  "missing_info": ["<uppgift eller dokument som saknas>", ...]\n'
    "}"
)


def _get_llm_key() -> str:
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        env_file = Path(__file__).parent.parent / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("DEEPSEEK_API_KEY="):
                    key = line.split("=", 1)[1].strip()
                    break
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY not set")
    return key


def _llm_json(system: str, user: str, max_tokens: int = 1200) -> Dict[str, Any]:
    r = httpx.post(
        LLM_URL,
        json={
            "model": CHAT_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": max_tokens,
        },
        headers={"Authorization": f"Bearer {_get_llm_key()}"},
        timeout=90,
    )
    r.raise_for_status()
    return json.loads(r.json()["choices"][0]["message"]["content"])


def keyword_category(text: str) -> str:
    t = (text or "").lower()
    if "vatten" in t or "läcka" in t or "rör" in t:
        return "Vattenskada"
    if "brand" in t or "rök" in t:
        return "Brand- eller rökskada"
    if "storm" in t or "tak" in t:
        return "Stormskada"
    if "stöld" in t or "inbrott" in t:
        return "Stöld- eller inbrottsskada"
    if "mögel" in t or "fukt" in t:
        return "Mögel eller fuktskada"
    return "Annan egendomsskada"


def categorize(description: str, hint: str = "") -> Dict[str, Any]:
    user = f"Skadebeskrivning:\n{description[:2000]}"
    if hint:
        user += f"\n\nKundens egen kategorisering: {hint}"
    try:
        out = _llm_json(CATEGORIZE_SYSTEM, user, max_tokens=100)
        category = out.get("category", "")
        if category in CATEGORIES:
            return {"category": category, "degraded": False}
    except Exception:
        pass
    return {"category": hint if hint in CATEGORIES else keyword_category(description), "degraded": True}


def assess(fields: Dict[str, Any], law_hits: List[Dict], arn_hits: List[Dict]) -> Dict[str, Any]:
    parts = [
        "ÄRENDE:",
        f"Kategori: {fields.get('damage_category')}",
        f"Beskrivning: {fields.get('damage_description', '')[:1500]}",
        f"Försäkringsbolag: {fields.get('insurance_company') or 'okänt'}",
        f"Yrkat belopp: {fields.get('claim_amount') or 'ej angivet'}",
        f"Bolagets beslut: {fields.get('insurer_decision') or 'inget ännu'}",
        f"Erbjudet belopp: {fields.get('insurer_amount') or 'ej angivet'}",
        f"Bolagets motivering: {fields.get('insurer_reason') or 'ingen'}",
        "\nRELEVANTA LAGRUM:",
    ]
    for h in law_hits:
        parts.append(f"** {h['title']} **\n{h['text'][:800]}")
    parts.append("\nRELEVANTA ARN-BESLUT:")
    for h in arn_hits:
        parts.append(f"** {h['title']} **\n{h['text'][:800]}")

    try:
        out = _llm_json(ASSESS_SYSTEM, "\n\n".join(parts))
        if out.get("strength") in ("stark", "medel", "svag"):
            return {
                "strength": out["strength"],
                "summary": str(out.get("summary", ""))[:1200],
                "key_arguments": [str(a) for a in out.get("key_arguments", [])][:6],
                "missing_info": [str(m) for m in out.get("missing_info", [])][:6],
                "degraded": False,
            }
    except Exception:
        pass
    return {
        "strength": "okänd",
        "summary": (
            "Vi har tagit emot ditt ärende och matchat det mot relevant lagstiftning "
            "och ARN-praxis. En handläggare går igenom ärendet och återkommer."
        ),
        "key_arguments": [],
        "missing_info": [],
        "degraded": True,
    }


def _new_case_id(db: Session) -> str:
    yymm = datetime.utcnow().strftime("%y%m")
    while True:
        candidate = f"SC-{yymm}-{random.randint(100, 999)}"
        if not db.query(Case).filter(Case.id == candidate).first():
            return candidate


def analyze(payload: Dict[str, Any], db: Session) -> Dict[str, Any]:
    description = payload.get("damage_description", "")
    cat = categorize(description, hint=payload.get("damage_category") or "")
    category = cat["category"]

    rag_query = f"{category} {description[:300]}"
    if payload.get("insurer_reason"):
        rag_query += f" {payload['insurer_reason'][:200]}"
    try:
        law_hits = [h for h in search_law(rag_query, k=8) if h["path"].startswith("Lagstiftning/")][:5]
        arn_hits = search_precedents(category, payload.get("insurer_reason") or description, k=5)
        rag_failed = False
    except Exception:
        law_hits, arn_hits, rag_failed = [], [], True

    fields = dict(payload, damage_category=category)
    assessment = assess(fields, law_hits, arn_hits) if not rag_failed else {
        "strength": "okänd",
        "summary": "Vi har tagit emot ditt ärende. En handläggare går igenom det och återkommer.",
        "key_arguments": [],
        "missing_info": [],
        "degraded": True,
    }

    analysis = {
        "category": category,
        "strength": assessment["strength"],
        "summary": assessment["summary"],
        "key_arguments": assessment["key_arguments"],
        "missing_info": assessment["missing_info"],
        "matched_laws": [
            {"ref": h["title"], "title": h["title"], "score": h["score"], "excerpt": h["text"][:300]}
            for h in law_hits
        ],
        "matched_precedents": [
            {"id": h["title"].replace("ARN ", ""), "title": h["title"], "score": h["score"], "excerpt": h["text"][:300]}
            for h in arn_hits
        ],
        "degraded": cat["degraded"] or assessment["degraded"] or rag_failed,
        "generated_at": datetime.utcnow().isoformat(),
    }

    case = Case(
        id=_new_case_id(db),
        customer_name=payload.get("customer_name", ""),
        customer_email=payload.get("customer_email", ""),
        customer_phone=payload.get("customer_phone", ""),
        property_address=payload.get("property_address", ""),
        property_type=payload.get("property_type", ""),
        insurance_company=payload.get("insurance_company", ""),
        insurance_policy_number="",
        insurance_type="",
        damage_category=category,
        damage_description=description,
        damage_date=payload.get("damage_date", ""),
        claim_amount=payload.get("claim_amount"),
        insurer_decision=payload.get("insurer_decision"),
        insurer_amount=payload.get("insurer_amount"),
        insurer_reason=payload.get("insurer_reason"),
        tags=payload.get("tags", []),
        ai_analysis=analysis,
    )
    db.add(case)
    db.commit()
    db.refresh(case)

    return {"case_id": case.id, **analysis}
