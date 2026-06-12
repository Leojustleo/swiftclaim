from app.draft_ai import DraftPlan, budget_evidence, fallback_plan


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
