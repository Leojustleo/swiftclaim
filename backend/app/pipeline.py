import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.draft_ai import case_fields, create_job, run_draft_job
from app.models import Case, DraftJob, PipelineJob
from app.scorecard import build_scorecard, degraded_scorecard, retrieve_evidence


def create_pipeline_job(db: Session, case_id: str) -> PipelineJob:
    job = PipelineJob(id=f"pl-{uuid.uuid4().hex[:12]}", case_id=case_id, status="queued", stages={})
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _set_stage(db: Session, job: PipelineJob, status: str, key: str, snapshot: Any) -> None:
    job.status = status
    stages = dict(job.stages or {})
    stages[key] = snapshot
    job.stages = stages
    job.updated_at = datetime.utcnow()
    db.commit()


def run_pipeline(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.query(PipelineJob).filter(PipelineJob.id == job_id).first()
        if not job:
            return
        case = db.query(Case).filter(Case.id == job.case_id).first()
        if not case:
            job.status, job.error = "failed", "case not found"
            db.commit()
            return
        try:
            _run_stages(db, job, case)
        except Exception as e:
            job.status, job.error = "failed", f"{type(e).__name__}: {e}"
            db.commit()
    finally:
        db.close()


def _run_stages(db: Session, job: PipelineJob, case: Case) -> None:
    fields = case_fields(case)

    if case.scorecard:
        _set_stage(db, job, "scoring", "scorecard", {"skipped": "case already scored"})
    else:
        job.status = "research"
        db.commit()
        law_hits, arn_hits, rag_failed = retrieve_evidence(fields)
        _set_stage(db, job, "research", "research", {
            "law_hits": [h["title"] for h in law_hits],
            "arn_hits": [h["title"] for h in arn_hits],
            "failed": rag_failed,
        })

        job.status = "scoring"
        db.commit()
        try:
            sc = build_scorecard(db, fields, law_hits=law_hits, arn_hits=arn_hits, job_id=job.id)
        except Exception as e:
            sc = degraded_scorecard(True)
            sc["error"] = f"{type(e).__name__}: {e}"
        case.scorecard = json.dumps(sc, ensure_ascii=False)
        _set_stage(db, job, "scoring", "scorecard", {
            "degraded": sc["degraded"],
            "claim_strength": sc["claim_strength"],
            "priority": sc["priority"],
        })

    job.status = "drafting"
    db.commit()
    try:
        draft_job = create_job(db, case.id, "maximize_payout", "")
        run_draft_job(draft_job.id)
        db.expire_all()
        dj = db.query(DraftJob).filter(DraftJob.id == draft_job.id).first()
        _set_stage(db, job, "drafting", "draft", {
            "draft_job_id": draft_job.id,
            "status": dj.status if dj else "missing",
            "error": dj.error if dj else None,
        })
    except Exception as e:
        _set_stage(db, job, "drafting", "draft",
                   {"status": "failed", "error": f"{type(e).__name__}: {e}"})

    case.status = "needs_review"
    job.status = "done"
    job.updated_at = datetime.utcnow()
    db.commit()
