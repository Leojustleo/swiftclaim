from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.draft_ai import DraftCitation, case_block, case_fields
from app.llm import LLMError, chat_json, scrub_pii, unscrub_pii
from app.models import ARNDecision, Case
from app.rag import DIR_MAP, get_index, search_vault
from app.verify import build_resolver, verify_citations

MIN_SCORE = 0.35
BROAD_MIN_SCORE = 0.30
BROAD_K = 14
BROAD_DOC_CHARS = 1200

BROAD_HINTS = (
    "vanligaste", "vanligast", "oftast", "flest", "mönster", "statistik",
    "brukar", "misstag", "trend", "generellt", "typiska", "typiskt",
    "hur många", "andel", "jämför", "skillnad mellan bolag", "i regel",
    "vilka fel", "sammanfatta", "överblick",
)


class QAOutput(BaseModel):
    answer_markdown: str
    citations: List[DraftCitation] = []


class ModeOut(BaseModel):
    mode: str


CLASSIFY_SYSTEM = """Klassificera frågan om svensk försäkringsjuridik i exakt ett läge:
- "lookup": frågan gäller en specifik regel, paragraf, situation eller ett enskilt ärende.
- "broad": frågan gäller mönster, statistik, jämförelser, vanliga fel eller en överblick över många fall.

Svara endast med JSON: {"mode": "lookup"} eller {"mode": "broad"}"""


ASK_SYSTEM = """Du är en svensk försäkringsjurist på Swiftclaim. Besvara frågan med stöd av ENDAST de numrerade källdokumenten nedan.

REGLER:
- Grunda varje påstående i källorna; hänvisa med exakta lagrum (t.ex. "FAL 4 kap 6 §") eller ARN-nummer.
- Om källorna inte räcker för att besvara frågan: säg det tydligt, förklara VARFÖR (vilken typ av information som saknas i kunskapsbasen) och vad som skulle behövas för att kunna svara.
- Hitta aldrig på lagrum eller rättsfall.

Svara endast med JSON:
{"answer_markdown": "<svar på svenska>", "citations": [{"ref": "<lagrum/ARN-nummer>", "doc_id": "<DOC-n eller null>"}]}"""


ASK_BROAD_SYSTEM = """Du är en svensk försäkringsjurist på Swiftclaim. Frågan är analytisk — besvara den genom att se mönster i vår kunskapsbas. Du får databasstatistik (fakta, exakta siffror) och utdrag ur källdokument.

REGLER:
- Grunda slutsatser ENDAST i statistiken och källdokumenten nedan. Dra rimliga mönster-slutsatser, men hitta aldrig på siffror, lagrum eller fall.
- Hänvisa till konkreta ARN-beslut (med nummer) eller lagrum som stöd där det går.
- Ange alltid databasens begränsning: vår samling är liten (antalet framgår av statistiken) och inte statistiskt representativ för hela marknaden.
- Om frågan kräver data vi inte har (t.ex. bolagens interna avslagsstatistik, totala skadevolymer): säg att det inte går att besvara, förklara exakt varför, och beskriv vad som ändå går att utläsa ur vår databas.

Svara endast med JSON:
{"answer_markdown": "<svar på svenska>", "citations": [{"ref": "<lagrum/ARN-nummer>", "doc_id": "<DOC-n eller null>"}]}"""


def heuristic_mode(question: str) -> str:
    q = (question or "").lower()
    return "broad" if any(h in q for h in BROAD_HINTS) else "lookup"


def classify_question(db: Session, question: str) -> str:
    try:
        out, _ = chat_json(CLASSIFY_SYSTEM, question[:500], ModeOut,
                           db=db, stage="ask.classify", max_tokens=20, timeout=30)
        if out.mode in ("lookup", "broad"):
            return out.mode
    except LLMError:
        pass
    return heuristic_mode(question)


def arn_stats(rows: List[dict]) -> Dict[str, Any]:
    outcomes: Counter = Counter()
    by_category: Dict[str, Counter] = {}
    legal_basis: Counter = Counter()
    keywords: Counter = Counter()
    for r in rows:
        outcome = r.get("outcome") or "okänt"
        outcomes[outcome] += 1
        cat = r.get("category") or "okänt"
        by_category.setdefault(cat, Counter())[outcome] += 1
        legal_basis.update(r.get("legal_basis") or [])
        keywords.update(r.get("keywords") or [])
    return {
        "total": len(rows),
        "outcomes": outcomes,
        "by_category": by_category,
        "top_legal_basis": legal_basis.most_common(8),
        "top_keywords": keywords.most_common(10),
    }


def corpus_overview(db: Session) -> str:
    notes, _ = get_index()
    counts = Counter()
    for n in notes:
        for name, prefix in DIR_MAP.items():
            if n["path"].startswith(prefix):
                counts[name] += 1
                break
    rows = [{
        "outcome": a.outcome, "category": a.category,
        "legal_basis": a.legal_basis or [], "keywords": a.keywords or [],
    } for a in db.query(ARNDecision).all()]
    stats = arn_stats(rows)

    lines = [
        "DATABASSTATISTIK (exakta fakta ur vår kunskapsbas):",
        "Innehåll: " + ", ".join(f"{counts.get(k, 0)} {label}" for k, label in [
            ("lagstiftning", "lagparagrafer"), ("arn", "ARN-beslut"), ("praxis", "rättsfall"),
            ("villkor", "villkorsdokument"), ("forarbeten", "förarbeten"), ("vagledning", "vägledningar"),
        ]),
        f"ARN-beslut i databasen: {stats['total']} st. Utfall: "
        + ", ".join(f"{k}: {v}" for k, v in stats["outcomes"].most_common()),
    ]
    if stats["by_category"]:
        lines.append("Utfall per kategori: " + "; ".join(
            f"{cat} ({', '.join(f'{o}: {n}' for o, n in c.most_common())})"
            for cat, c in stats["by_category"].items()
        ))
    if stats["top_legal_basis"]:
        lines.append("Oftast åberopade lagrum i ARN-besluten: "
                     + ", ".join(f"{ref} ({n} ggr)" for ref, n in stats["top_legal_basis"]))
    if stats["top_keywords"]:
        lines.append("Vanligaste nyckelord i ARN-besluten: "
                     + ", ".join(f"{kw} ({n})" for kw, n in stats["top_keywords"]))
    return "\n".join(lines)


def _evidence_from_hits(hits: List[dict], max_chars: int) -> List[dict]:
    return [{
        "doc_id": f"DOC-{i + 1}", "path": h["path"], "title": h["title"],
        "score": h["score"], "source_url": h.get("source_url"), "text": h["text"][:max_chars],
    } for i, h in enumerate(hits)]


def _docs_block(evidence: List[dict]) -> str:
    return "\n\n---\n\n".join(
        f"[{d['doc_id']}] {d['title']}" + (f" (källa: {d['source_url']})" if d["source_url"] else "") + f"\n{d['text']}"
        for d in evidence
    )


def ask(db: Session, question: str, case: Optional[Case] = None) -> Dict[str, Any]:
    fields = case_fields(case) if case else {}
    q = scrub_pii(question, fields) if case else question
    mode = classify_question(db, q)

    if mode == "broad":
        hits = search_vault(q, k=BROAD_K, min_score=BROAD_MIN_SCORE)
        evidence = _evidence_from_hits(hits, BROAD_DOC_CHARS)
        parts = [corpus_overview(db), f"FRÅGA:\n{q}"]
        if evidence:
            parts.append(f"KÄLLDOKUMENT (utdrag):\n\n{_docs_block(evidence)}")
        system = ASK_BROAD_SYSTEM
        stage = "ask.broad"
    else:
        rag_query = f"{fields.get('damage_category', '')} {q}".strip() if case else q
        hits = search_vault(rag_query, k=8, min_score=MIN_SCORE)
        if not hits:
            return {
                "answer_markdown": (
                    "Hittade inga relevanta källor i kunskapsbasen för frågan. "
                    "Kunskapsbasen täcker svensk försäkringsjuridik: lagparagrafer, ARN-beslut, "
                    "rättsfall, försäkringsvillkor, förarbeten och vägledningar. "
                    "Formulera gärna om frågan med juridiska termer eller mer detaljer om skadan."
                ),
                "sources": [], "unverified_refs": [], "model_used": None, "mode": mode,
            }
        evidence = _evidence_from_hits(hits, 2000)
        parts = []
        if case:
            parts.append(case_block(fields))
        parts.append(f"FRÅGA:\n{q}")
        parts.append(f"KÄLLDOKUMENT:\n\n{_docs_block(evidence)}")
        system = ASK_SYSTEM
        stage = "ask"

    out, meta = chat_json(system, "\n\n".join(parts), QAOutput,
                          db=db, stage=stage, max_tokens=1500)

    resolver = build_resolver(db, {d["doc_id"] for d in evidence})
    verified, flagged = verify_citations([c.model_dump() for c in out.citations], resolver)

    by_doc = {d["doc_id"]: d for d in evidence}
    by_title = {d["title"].lower(): d for d in evidence}
    sources = []
    for v in verified:
        doc = by_doc.get((v.get("doc_id") or "").upper()) or by_title.get(v["ref"].lower())
        sources.append({
            "ref": v["ref"],
            "title": doc["title"] if doc else v["ref"],
            "path": doc["path"] if doc else "",
            "score": doc["score"] if doc else 0.0,
            "source_url": doc["source_url"] if doc else None,
        })

    return {
        "answer_markdown": unscrub_pii(out.answer_markdown, fields),
        "sources": sources,
        "unverified_refs": flagged,
        "model_used": meta["model"],
        "mode": mode,
    }
