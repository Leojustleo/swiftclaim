from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.draft_ai import DraftCitation, case_block, case_fields
from app.llm import chat_json, scrub_pii, unscrub_pii
from app.models import Case
from app.rag import search_vault
from app.verify import build_resolver, verify_citations

MIN_SCORE = 0.35


class QAOutput(BaseModel):
    answer_markdown: str
    citations: List[DraftCitation] = []


ASK_SYSTEM = """Du är en svensk försäkringsjurist på Swiftclaim. Besvara frågan med stöd av ENDAST de numrerade källdokumenten nedan.

REGLER:
- Grunda varje påstående i källorna; hänvisa med exakta lagrum (t.ex. "FAL 4 kap 6 §") eller ARN-nummer.
- Om källorna inte räcker för att besvara frågan: säg det tydligt i svaret.
- Hitta aldrig på lagrum eller rättsfall.

Svara endast med JSON:
{"answer_markdown": "<svar på svenska>", "citations": [{"ref": "<lagrum/ARN-nummer>", "doc_id": "<DOC-n eller null>"}]}"""


def ask(db: Session, question: str, case: Optional[Case] = None) -> Dict[str, Any]:
    fields = case_fields(case) if case else {}
    q = scrub_pii(question, fields) if case else question
    rag_query = f"{fields.get('damage_category', '')} {q}".strip() if case else q

    hits = search_vault(rag_query, k=8, min_score=MIN_SCORE)
    if not hits:
        return {
            "answer_markdown": "Hittade inga relevanta källor i kunskapsbasen för frågan. Formulera gärna om frågan eller ange mer detaljer.",
            "sources": [], "unverified_refs": [], "model_used": None,
        }

    evidence = [{
        "doc_id": f"DOC-{i + 1}", "path": h["path"], "title": h["title"],
        "score": h["score"], "source_url": h.get("source_url"), "text": h["text"][:2000],
    } for i, h in enumerate(hits)]

    docs = "\n\n---\n\n".join(
        f"[{d['doc_id']}] {d['title']}" + (f" (källa: {d['source_url']})" if d["source_url"] else "") + f"\n{d['text']}"
        for d in evidence
    )
    parts = []
    if case:
        parts.append(case_block(fields))
    parts.append(f"FRÅGA:\n{q}")
    parts.append(f"KÄLLDOKUMENT:\n\n{docs}")

    out, meta = chat_json(ASK_SYSTEM, "\n\n".join(parts), QAOutput,
                          db=db, stage="ask", max_tokens=1500)

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
    }
