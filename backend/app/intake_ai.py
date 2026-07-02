import json
import random
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.llm import LLMError, chat_json, scrub_pii
from app.models import Case
from app.scorecard import build_scorecard, retrieve_evidence


class CategorizeOut(BaseModel):
    category: str

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


def categorize(description: str, hint: str = "",
               fields: Optional[Dict[str, Any]] = None, db: Session = None) -> Dict[str, Any]:
    safe = scrub_pii(description, fields or {})
    user = f"Skadebeskrivning:\n{safe[:2000]}"
    if hint:
        user += f"\n\nKundens egen kategorisering: {hint}"
    try:
        out, _ = chat_json(CATEGORIZE_SYSTEM, user, CategorizeOut,
                           db=db, stage="intake.categorize", max_tokens=100)
        if out.category in CATEGORIES:
            return {"category": out.category, "degraded": False}
    except LLMError:
        pass
    return {"category": hint if hint in CATEGORIES else keyword_category(description), "degraded": True}


def assess(fields: Dict[str, Any], law_hits: List[Dict], arn_hits: List[Dict],
           db: Session = None) -> Dict[str, Any]:
    sc = build_scorecard(db, fields, law_hits=law_hits, arn_hits=arn_hits)
    return {
        "strength": sc["strength_band"],
        "summary": sc["summary"],
        "key_arguments": sc["key_factors"][:6],
        "missing_info": sc["missing_info"][:6],
        "degraded": sc["degraded"],
        "scorecard": sc,
    }


def _new_case_id(db: Session) -> str:
    yymm = datetime.utcnow().strftime("%y%m")
    for _ in range(40):
        candidate = f"SC-{yymm}-{random.randint(100, 999)}"
        if not db.query(Case).filter(Case.id == candidate).first():
            return candidate
    return f"SC-{yymm}-{uuid.uuid4().hex[:6]}"


def analyze(payload: Dict[str, Any], db: Session) -> Dict[str, Any]:
    description = payload.get("damage_description", "")
    cat = categorize(description, hint=payload.get("damage_category") or "",
                     fields=payload, db=db)
    category = cat["category"]

    law_hits, arn_hits, rag_failed = retrieve_evidence(dict(payload, damage_category=category))

    fields = dict(payload, damage_category=category)
    assessment = assess(fields, law_hits, arn_hits, db=db) if not rag_failed else {
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

    sc = assessment.get("scorecard")
    case = Case(
        id=_new_case_id(db),
        scorecard=json.dumps(sc, ensure_ascii=False) if sc else None,
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
