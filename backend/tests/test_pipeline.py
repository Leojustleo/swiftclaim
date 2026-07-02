import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app import pipeline
from app.models import Case, DraftJob


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _case(db, **kw):
    c = Case(id="SC-2607-123", customer_name="A", insurance_company="If",
             damage_category="Vattenskada", damage_description="läcka", **kw)
    db.add(c)
    db.commit()
    return c


def _fake_draft(db, monkeypatch, final_status="done", error=None):
    def fake_create_job(d, case_id, strategy, ctx):
        dj = DraftJob(id="dj-1", case_id=case_id, status="queued")
        d.add(dj)
        d.commit()
        return dj

    def fake_run_draft_job(job_id):
        dj = db.query(DraftJob).filter(DraftJob.id == job_id).first()
        dj.status, dj.error = final_status, error
        db.commit()

    monkeypatch.setattr(pipeline, "create_job", fake_create_job)
    monkeypatch.setattr(pipeline, "run_draft_job", fake_run_draft_job)


def test_happy_path_lands_in_review_queue(db, monkeypatch):
    case = _case(db)
    job = pipeline.create_pipeline_job(db, case.id)
    monkeypatch.setattr(pipeline, "retrieve_evidence", lambda f: ([], [], False))
    monkeypatch.setattr(pipeline, "build_scorecard",
                        lambda d, f, **kw: {"claim_strength": 80, "priority": "high", "degraded": False})
    _fake_draft(db, monkeypatch)

    pipeline._run_stages(db, job, case)

    assert job.status == "done"
    assert case.status == "needs_review"
    assert json.loads(case.scorecard)["claim_strength"] == 80
    assert job.stages["draft"]["status"] == "done"


def test_scorecard_crash_still_reaches_queue(db, monkeypatch):
    case = _case(db)
    job = pipeline.create_pipeline_job(db, case.id)
    monkeypatch.setattr(pipeline, "retrieve_evidence", lambda f: ([], [], False))

    def boom(*a, **kw):
        raise RuntimeError("scoring exploded")

    monkeypatch.setattr(pipeline, "build_scorecard", boom)
    _fake_draft(db, monkeypatch)

    pipeline._run_stages(db, job, case)

    assert job.status == "done"
    assert case.status == "needs_review"
    sc = json.loads(case.scorecard)
    assert sc["degraded"] is True
    assert "scoring exploded" in sc["error"]


def test_draft_crash_still_reaches_queue_with_scorecard(db, monkeypatch):
    case = _case(db)
    job = pipeline.create_pipeline_job(db, case.id)
    monkeypatch.setattr(pipeline, "retrieve_evidence", lambda f: ([], [], False))
    monkeypatch.setattr(pipeline, "build_scorecard",
                        lambda d, f, **kw: {"claim_strength": 55, "priority": "medium", "degraded": False})

    def boom(*a, **kw):
        raise RuntimeError("draft exploded")

    monkeypatch.setattr(pipeline, "create_job", boom)

    pipeline._run_stages(db, job, case)

    assert job.status == "done"
    assert case.status == "needs_review"
    assert json.loads(case.scorecard)["claim_strength"] == 55
    assert job.stages["draft"]["status"] == "failed"
    assert "draft exploded" in job.stages["draft"]["error"]


def test_already_scored_case_skips_research_and_scoring(db, monkeypatch):
    case = _case(db, scorecard='{"claim_strength": 90, "priority": "high"}')
    job = pipeline.create_pipeline_job(db, case.id)

    def boom(*a, **kw):
        raise AssertionError("should not run")

    monkeypatch.setattr(pipeline, "retrieve_evidence", boom)
    monkeypatch.setattr(pipeline, "build_scorecard", boom)
    _fake_draft(db, monkeypatch)

    pipeline._run_stages(db, job, case)

    assert job.status == "done"
    assert case.status == "needs_review"
    assert job.stages["scorecard"]["skipped"] == "case already scored"
