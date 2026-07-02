import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.llm import LLMError, chat_json, scrub_pii
from app.rag import search_law, search_precedents
from app.verify import build_resolver


class ScorecardOut(BaseModel):
    claim_strength: int
    win_probability: str
    summary: str = ""
    key_factors: List[str] = []
    recommended_action: str = ""
    missing_info: List[str] = []
    arn_references: List[str] = []
    lagrum_references: List[str] = []


SCORECARD_SYSTEM = (
    "Du är en svensk försäkringsjurist på Swiftclaim. Bedöm ärendet mot lagrum "
    "och ARN-praxis nedan. Var saklig, lova aldrig ett utfall, och hänvisa bara "
    "till lagrum och ARN-beslut som citeras i underlaget.\n\n"
    "Svara endast med JSON:\n"
    "{\n"
    '  "claim_strength": <heltal 0-100>,\n'
    '  "win_probability": "<procent som sträng, t.ex. \'65%\'>",\n'
    '  "summary": "<2-4 meningar på svenska riktade till kunden: vad vi ser i ärendet>",\n'
    '  "key_factors": ["<faktor>", ...],\n'
    '  "recommended_action": "<max 2 meningar, hänvisa till ARN-beslut om möjligt>",\n'
    '  "missing_info": ["<uppgift eller dokument som saknas>", ...],\n'
    '  "arn_references": ["<ARN-nummer, t.ex. 2020-08495>", ...],\n'
    '  "lagrum_references": ["<t.ex. FAL 4 kap 6 §>", ...]\n'
    "}"
)


def band_from_strength(strength: Optional[int]) -> str:
    if strength is None:
        return "okänd"
    if strength >= 70:
        return "stark"
    if strength >= 40:
        return "medel"
    return "svag"


def priority_from_strength(strength: Optional[int]) -> str:
    if strength is None:
        return "unknown"
    if strength >= 70:
        return "high"
    if strength >= 40:
        return "medium"
    return "low"


def retrieve_evidence(fields: Dict[str, Any]) -> Tuple[List[Dict], List[Dict], bool]:
    category = fields.get("damage_category") or ""
    safe_desc = scrub_pii(fields.get("damage_description") or "", fields)
    query = f"{category} {safe_desc[:300]}"
    reason = fields.get("insurer_reason") or ""
    if reason:
        query += f" {scrub_pii(reason, fields)[:200]}"
    try:
        law_hits = [h for h in search_law(query, k=8) if h["path"].startswith("Lagstiftning/")][:5]
        arn_hits = search_precedents(category, scrub_pii(reason or safe_desc, fields), k=5)
        return law_hits, arn_hits, False
    except Exception:
        return [], [], True


def _case_block(fields: Dict[str, Any]) -> str:
    return "\n".join([
        "ÄRENDE:",
        f"Kategori: {fields.get('damage_category') or '—'}",
        f"Försäkringsbolag: {fields.get('insurance_company') or 'okänt'}",
        f"Yrkat belopp: {fields.get('claim_amount') or 'ej angivet'}",
        f"Erbjudet belopp: {fields.get('insurer_amount') or 'ej angivet'}",
        f"Bolagets beslut: {fields.get('insurer_decision') or 'inget ännu'}",
        f"Bolagets motivering: {fields.get('insurer_reason') or 'ingen'}",
        f"Beskrivning: {(fields.get('damage_description') or '')[:1500]}",
    ])


def _resolve_references(db, arn_references: List[str],
                        lagrum_references: List[str]) -> Tuple[List[str], List[str], List[str]]:
    try:
        resolver = build_resolver(db, set())
    except Exception:
        # No resolver → nothing is verified; surface every ref as unverified.
        return [], [], [str(r) for r in list(arn_references) + list(lagrum_references)]
    arn_refs: List[str] = []
    lagrum_refs: List[str] = []
    flagged: List[str] = []
    for ref in arn_references:
        hit = resolver.resolve(str(ref))
        (arn_refs.append(hit["ref"]) if hit else flagged.append(str(ref)))
    for ref in lagrum_references:
        hit = resolver.resolve(str(ref))
        (lagrum_refs.append(hit["ref"]) if hit else flagged.append(str(ref)))
    return arn_refs, lagrum_refs, flagged


def degraded_scorecard(rag_failed: bool = False) -> Dict[str, Any]:
    return {
        "claim_strength": None,
        "strength_band": "okänd",
        "win_probability": None,
        "priority": "unknown",
        "summary": "Vi har tagit emot ditt ärende. En handläggare går igenom det och återkommer.",
        "key_factors": [],
        "recommended_action": "",
        "missing_info": [],
        "arn_references": [],
        "lagrum_references": [],
        "flagged_references": [],
        "degraded": True,
        "generated_at": datetime.utcnow().isoformat(),
    }


def build_scorecard(db: Optional[Session], fields: Dict[str, Any],
                    law_hits: Optional[List[Dict]] = None,
                    arn_hits: Optional[List[Dict]] = None,
                    job_id: Optional[str] = None) -> Dict[str, Any]:
    if law_hits is None or arn_hits is None:
        law_hits, arn_hits, rag_failed = retrieve_evidence(fields)
    else:
        rag_failed = False

    parts = [_case_block(fields), "\nRELEVANTA LAGRUM:"]
    for h in law_hits:
        parts.append(f"** {h['title']} **\n{h['text'][:800]}")
    parts.append("\nRELEVANTA ARN-BESLUT:")
    for h in arn_hits:
        parts.append(f"** {h['title']} **\n{h['text'][:800]}")

    try:
        out, _ = chat_json(SCORECARD_SYSTEM, scrub_pii("\n\n".join(parts), fields),
                           ScorecardOut, db=db, job_id=job_id,
                           stage="scorecard", max_tokens=1500)
    except LLMError:
        return degraded_scorecard(rag_failed)

    strength = max(0, min(100, int(out.claim_strength)))
    arn_refs, lagrum_refs, flagged = _resolve_references(db, out.arn_references, out.lagrum_references)
    return {
        "claim_strength": strength,
        "strength_band": band_from_strength(strength),
        "win_probability": out.win_probability,
        "priority": priority_from_strength(strength),
        "summary": out.summary[:1200],
        "key_factors": [str(f) for f in out.key_factors][:6],
        "recommended_action": out.recommended_action[:500],
        "missing_info": [str(m) for m in out.missing_info][:6],
        "arn_references": arn_refs,
        "lagrum_references": lagrum_refs,
        "flagged_references": flagged,
        "degraded": rag_failed,
        "generated_at": datetime.utcnow().isoformat(),
    }


def parse_probability(value: Any) -> Optional[int]:
    digits = re.sub(r"[^0-9]", "", str(value or ""))
    if not digits:
        return None
    return max(0, min(100, int(digits[:3])))


CALIBRATION_BUCKETS = [(0, 39, "0-39"), (40, 59, "40-59"), (60, 79, "60-79"), (80, 100, "80-100")]


def calibration_buckets(rows: List[Tuple[Any, Optional[str]]]) -> Dict[str, Dict[str, int]]:
    out = {label: {"n": 0, "wins": 0} for _, _, label in CALIBRATION_BUCKETS}
    for prob, outcome in rows:
        p = parse_probability(prob)
        if p is None or outcome not in ("won", "partial", "lost"):
            continue
        for lo, hi, label in CALIBRATION_BUCKETS:
            if lo <= p <= hi:
                out[label]["n"] += 1
                if outcome in ("won", "partial"):
                    out[label]["wins"] += 1
                break
    return out
