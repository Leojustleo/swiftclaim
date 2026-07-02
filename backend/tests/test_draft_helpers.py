from datetime import datetime, timedelta
from types import SimpleNamespace

from app.draft_ai import DraftPlan, budget_evidence, fallback_plan, fail_if_stale


def test_fallback_plan_always_valid():
    plan = fallback_plan({"damage_category": "Vattenskada", "damage_description": "Läcka i köket", "insurer_reason": "åldersavdrag 80%"})
    assert isinstance(plan, DraftPlan)
    assert 1 <= len(plan.arguments) <= 4
    assert all(a.queries for a in plan.arguments)


def _hit(path, score, chars=3000):
    return {"path": path, "title": path.split("/")[-1], "score": score, "text": "x" * chars, "source_url": None}


def test_budget_evidence_dedupes_caps_and_numbers():
    per_query = [
        [_hit("Lagstiftning/A", 0.9), _hit("Lagstiftning/B", 0.8)],
        [_hit("Lagstiftning/A", 0.7), _hit("ARN/C", 0.6)],
    ]
    docs = budget_evidence(per_query, max_docs=2, max_chars=100)
    assert [d["doc_id"] for d in docs] == ["DOC-1", "DOC-2"]
    assert [d["path"] for d in docs] == ["Lagstiftning/A", "Lagstiftning/B"]
    assert all(len(d["text"]) <= 100 for d in docs)


class FakeDB:
    def __init__(self):
        self.committed = False

    def commit(self):
        self.committed = True


def _job(status, minutes_ago):
    return SimpleNamespace(
        status=status, error=None,
        updated_at=datetime.utcnow() - timedelta(minutes=minutes_ago),
        created_at=datetime.utcnow() - timedelta(minutes=minutes_ago),
    )


def test_stale_running_job_marked_failed():
    db, job = FakeDB(), _job("planning", 30)
    fail_if_stale(db, job)
    assert job.status == "failed"
    assert "stalled" in job.error
    assert db.committed


def test_fresh_and_terminal_jobs_untouched():
    db = FakeDB()
    fresh = _job("drafting", 2)
    fail_if_stale(db, fresh)
    assert fresh.status == "drafting"
    done = _job("done", 60)
    fail_if_stale(db, done)
    assert done.status == "done"
    assert not db.committed
