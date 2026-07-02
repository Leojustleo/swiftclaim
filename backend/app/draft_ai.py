from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.llm import LLMError, PIPELINE_VERSION, chat_json, scrub_pii, unscrub_pii
from app.models import Case, DraftJob, ResponseDraft
from app.rag import DIR_MAP, embed_queries, search_with_embedding
from app.verify import build_resolver, verify_citations

MIN_SCORE = 0.35
MAX_DOCS = 12
MAX_DOC_CHARS = 2500
MAX_QUERIES = 6

STALE_JOB_MINUTES = 15


class PlanArgument(BaseModel):
    claim: str
    queries: List[str] = Field(min_length=1, max_length=3)
    dataset_types: List[str] = []


class DraftPlan(BaseModel):
    arguments: List[PlanArgument] = Field(min_length=1, max_length=4)
    missing_info: List[str] = []


class DraftCitation(BaseModel):
    ref: str
    doc_id: Optional[str] = None


class DraftLetter(BaseModel):
    subject: str
    body_markdown: str


class DraftOutput(BaseModel):
    strategy_note: str
    letter: DraftLetter
    citations: List[DraftCitation] = []
    demands: List[str] = []
    deadline_days: int = 14


PLAN_SYSTEM = """Du är en svensk försäkringsjurist på Swiftclaim. Planera argumentationen för ett brev till försäkringsbolaget som kräver högre ersättning.

Tillgängliga kunskapskällor (dataset_types):
- lagstiftning: svenska lagparagrafer (FAL, Avtalslagen, Jordabalken m.fl.)
- arn: ARN-nämndbeslut (prejudikat)
- praxis: domstolspraxis (NJA m.m.)
- villkor: försäkringsbolagens villkorstexter
- forarbeten: propositioner och förarbeten
- vagledning: myndighetsvägledning

Svara endast med JSON:
{
  "arguments": [
    {"claim": "<juridiskt argument på svenska>",
     "queries": ["<sökfråga på svenska>", ...],
     "dataset_types": ["lagstiftning", "arn", ...]}
  ],
  "missing_info": ["<uppgift som saknas>", ...]
}
Max 4 argument. 1-3 sökfrågor per argument, max 6 totalt. Välj dataset_types som passar argumentet."""


DRAFT_SYSTEM = """Du är en erfaren svensk försäkringsjurist på Swiftclaim. Skriv ett professionellt brev till försäkringsbolaget som bestrider deras beslut och kräver rätt ersättning.

REGLER:
- Grunda VARJE juridiskt påstående i de numrerade källdokumenten [DOC-n] eller i exakta lagrum.
- Citera lagrum exakt (t.ex. "FAL 4 kap 6 §") och ARN-beslut med nummer (t.ex. "ARN 2018-11707").
- Hitta ALDRIG på lagrum, rättsfall eller villkor som inte finns i källorna.
- Kunden heter [KUND] — använd platshållaren exakt så i brevet.
- Professionell men bestämd ton. Konkreta yrkanden. Svarsfrist.

Svara endast med JSON:
{
  "strategy_note": "<intern strateginot på svenska>",
  "letter": {"subject": "<ärenderubrik>", "body_markdown": "<komplett brevtext på svenska>"},
  "citations": [{"ref": "<lagrum eller ARN-nummer>", "doc_id": "<DOC-n eller null>"}],
  "demands": ["<yrkande>", ...],
  "deadline_days": 14
}
Lista i citations VARJE lagrum och ARN-beslut som nämns i brevet."""


REPAIR_SYSTEM = """Du är en svensk försäkringsjurist. Brevet nedan innehåller hänvisningar som INTE kunde verifieras mot vår rättsdatabas. Skriv om brevet: ersätt varje overifierad hänvisning med en verifierad källa från listan, eller ta bort påståendet helt. Ändra inget annat.

Svara endast med JSON i samma schema som tidigare:
{"strategy_note": "...", "letter": {"subject": "...", "body_markdown": "..."}, "citations": [{"ref": "...", "doc_id": null}], "demands": ["..."], "deadline_days": 14}"""


def case_fields(case: Case) -> Dict[str, Any]:
    return {
        "customer_name": case.customer_name,
        "customer_email": case.customer_email,
        "customer_phone": case.customer_phone,
        "property_address": case.property_address,
        "insurance_company": case.insurance_company,
        "insurance_policy_number": case.insurance_policy_number,
        "damage_category": case.damage_category,
        "damage_description": case.damage_description or "",
        "damage_date": case.damage_date,
        "claim_amount": case.claim_amount,
        "insurer_decision": case.insurer_decision,
        "insurer_amount": case.insurer_amount,
        "insurer_reason": case.insurer_reason or "",
    }


def case_block(fields: Dict[str, Any]) -> str:
    raw = "\n".join([
        "ÄRENDE:",
        f"Kund: {fields['customer_name'] or 'okänd'}",
        f"Försäkringsbolag: {fields['insurance_company'] or 'okänt'}",
        f"Försäkringsnummer: {fields['insurance_policy_number'] or 'okänt'}",
        f"Typ av skada: {fields['damage_category'] or 'okänd'}",
        f"Skadebeskrivning: {fields['damage_description'][:1500]}",
        f"Skadedatum: {fields['damage_date'] or 'okänt'}",
        f"Yrkat belopp: {fields['claim_amount'] or 'ej specificerat'} kr",
        f"Bolagets beslut: {fields['insurer_decision'] or 'okänt'}",
        f"Bolagets motivering: {fields['insurer_reason'][:800] or 'ingen angiven'}",
        f"Erbjudet belopp: {fields['insurer_amount'] or 'ej specificerat'} kr",
    ])
    return scrub_pii(raw, fields)


def fallback_plan(fields: Dict[str, Any]) -> DraftPlan:
    queries = [f"{fields.get('damage_category', '')} {fields.get('damage_description', '')[:200]}".strip()]
    if fields.get("insurer_reason"):
        queries.append(f"nedsättning ersättning {fields['insurer_reason'][:150]}")
    else:
        queries.append(f"försäkringsersättning {fields.get('damage_category', '')}")
    return DraftPlan(arguments=[PlanArgument(
        claim="Rätt till full ersättning enligt försäkringsavtalet och FAL",
        queries=queries[:3],
        dataset_types=list(DIR_MAP.keys()),
    )])


def budget_evidence(per_query_hits: List[List[dict]], max_docs: int = MAX_DOCS,
                    max_chars: int = MAX_DOC_CHARS) -> List[dict]:
    best: Dict[str, dict] = {}
    for hits in per_query_hits:
        for h in hits:
            cur = best.get(h["path"])
            if cur is None or h["score"] > cur["score"]:
                best[h["path"]] = h
    ranked = sorted(best.values(), key=lambda h: -h["score"])[:max_docs]
    return [{
        "doc_id": f"DOC-{i + 1}",
        "path": h["path"],
        "title": h["title"],
        "score": h["score"],
        "source_url": h.get("source_url"),
        "text": h["text"][:max_chars],
    } for i, h in enumerate(ranked)]


def evidence_block(evidence: List[dict]) -> str:
    parts = []
    for d in evidence:
        src = f" (källa: {d['source_url']})" if d.get("source_url") else ""
        parts.append(f"[{d['doc_id']}] {d['title']}{src}\n{d['text']}")
    return "\n\n---\n\n".join(parts) if parts else "(inga källdokument hittades)"


def _set_stage(db: Session, job: DraftJob, status: str, key: str, snapshot: Any) -> None:
    job.status = status
    job.stages = {**(job.stages or {}), key: snapshot}
    job.updated_at = datetime.utcnow()
    db.commit()


def fail_if_stale(db: Session, job: DraftJob) -> DraftJob:
    if job.status in ("done", "failed"):
        return job
    ts = job.updated_at or job.created_at
    if ts and datetime.utcnow() - ts > timedelta(minutes=STALE_JOB_MINUTES):
        job.status, job.error = "failed", "job stalled — server likely restarted mid-run"
        db.commit()
    return job


def run_draft_job(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.query(DraftJob).filter(DraftJob.id == job_id).first()
        if not job:
            return
        case = db.query(Case).filter(Case.id == job.case_id).first()
        if not case:
            job.status, job.error = "failed", "case not found"
            db.commit()
            return
        try:
            _run_stages(db, job, case)
        except LLMError as e:
            job.status, job.error = "failed", f"LLM providers exhausted: {e}"
            db.commit()
        except Exception as e:
            job.status, job.error = "failed", f"{type(e).__name__}: {e}"
            db.commit()
    finally:
        db.close()


def _run_stages(db: Session, job: DraftJob, case: Case) -> None:
    fields = case_fields(case)
    request = (job.stages or {}).get("request", {})

    # 1 PLAN
    job.status = "planning"
    db.commit()
    plan_degraded = False
    try:
        plan, _ = chat_json(PLAN_SYSTEM, case_block(fields), DraftPlan,
                            db=db, job_id=job.id, stage="draft.plan", max_tokens=1200)
    except LLMError:
        plan, plan_degraded = fallback_plan(fields), True
    _set_stage(db, job, "planning", "plan", {"degraded": plan_degraded, **plan.model_dump()})

    # 2 RETRIEVE
    job.status = "retrieving"
    db.commit()
    tasks: List[Tuple[str, Optional[List[str]]]] = []
    for arg in plan.arguments:
        dirs = [d for d in arg.dataset_types if d in DIR_MAP] or None
        for q in arg.queries:
            if len(tasks) < MAX_QUERIES and q.strip():
                tasks.append((scrub_pii(q, fields), dirs))
    embeddings = embed_queries([q for q, _ in tasks])
    per_query = [search_with_embedding(emb, dirs=dirs, k=4, min_score=MIN_SCORE, query_text=q)
                 for emb, (q, dirs) in zip(embeddings, tasks)]
    evidence = budget_evidence(per_query)
    _set_stage(db, job, "retrieving", "retrieval", {
        "queries": [q for q, _ in tasks],
        "docs": [{k: d[k] for k in ("doc_id", "path", "title", "score", "source_url")} for d in evidence],
    })

    # 3 DRAFT
    job.status = "drafting"
    db.commit()
    user_msg = "\n\n".join([
        case_block(fields),
        "ARGUMENTPLAN:\n" + "\n".join(f"- {a.claim}" for a in plan.arguments),
        "KÄLLDOKUMENT:\n\n" + evidence_block(evidence),
        f"Strategi: {request.get('strategy', 'maximize_payout')}",
        f"Ytterligare kontext: {scrub_pii(request.get('additional_context') or 'ingen', fields)}",
    ])
    out, meta = chat_json(DRAFT_SYSTEM, user_msg, DraftOutput,
                          db=db, job_id=job.id, stage="draft.write", max_tokens=6000)
    _set_stage(db, job, "drafting", "draft", {"model": meta["model"], "subject": out.letter.subject})

    # 4 VERIFY (+ repair) + SAVE
    job.status = "verifying"
    db.commit()
    evidence_ids = {d["doc_id"] for d in evidence}
    resolver = build_resolver(db, evidence_ids)
    verified, flagged = verify_citations([c.model_dump() for c in out.citations], resolver)
    repaired = False
    if flagged:
        valid_refs = [v["ref"] for v in verified] + [f"{d['doc_id']}: {d['title']}" for d in evidence]
        repair_msg = "\n\n".join([
            "BREV:\n" + out.letter.body_markdown,
            "OVERIFIERADE HÄNVISNINGAR:\n" + "\n".join(f"- {f}" for f in flagged),
            "VERIFIERADE KÄLLOR:\n" + "\n".join(f"- {r}" for r in valid_refs),
        ])
        try:
            out, meta = chat_json(REPAIR_SYSTEM, repair_msg, DraftOutput,
                                  db=db, job_id=job.id, stage="draft.repair")
            verified, flagged = verify_citations([c.model_dump() for c in out.citations], resolver)
            repaired = True
        except LLMError:
            pass  # flag-only path: draft saved as needs_review below
    _set_stage(db, job, "verifying", "verify", {
        "verified": [v["ref"] for v in verified], "flagged": flagged, "repaired": repaired,
    })

    force_review = not evidence
    letter_text = unscrub_pii(f"Ärende: {out.letter.subject}\n\n{out.letter.body_markdown}", fields)
    prev = db.query(ResponseDraft).filter(ResponseDraft.case_id == case.id) \
        .order_by(ResponseDraft.version.desc()).first()
    draft = ResponseDraft(
        case_id=case.id,
        version=(prev.version + 1) if prev else 1,
        strategy=out.strategy_note,
        draft_text=letter_text,
        citations_used=[v["ref"] for v in verified],
        flagged_citations=flagged,
        evidence=[{k: d[k] for k in ("doc_id", "path", "title", "score", "source_url")} for d in evidence],
        model_used=meta["model"],
        job_id=job.id,
        status="needs_review" if (flagged or force_review) else "draft",
    )
    db.add(draft)
    case.status = "draft"
    case.updated_at = datetime.utcnow()
    db.flush()
    job.status = "done"
    job.draft_id = draft.id
    job.pipeline_version = PIPELINE_VERSION
    job.updated_at = datetime.utcnow()
    db.commit()


def create_job(db: Session, case_id: str, strategy: str, additional_context: str) -> DraftJob:
    job = DraftJob(
        id=uuid.uuid4().hex,
        case_id=case_id,
        status="queued",
        stages={"request": {"strategy": strategy, "additional_context": additional_context}},
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job
