import re

from app import intake_ai

FIELDS = {
    "customer_name": "Anna Andersson",
    "customer_email": "anna@example.se",
    "customer_phone": "0701234567",
    "property_address": "Storgatan 1, Lund",
    "insurance_policy_number": "HF-99887766",
}


def test_categorize_scrubs_pii(monkeypatch):
    captured = {}

    def fake_chat(system, user, schema, **kw):
        captured["user"] = user
        return schema(category="Vattenskada"), {"model": "m"}

    monkeypatch.setattr(intake_ai, "chat_json", fake_chat)
    out = intake_ai.categorize(
        "Anna Andersson fick vattenskada på Storgatan 1, Lund", fields=FIELDS)
    assert "Anna" not in captured["user"]
    assert "Storgatan" not in captured["user"]
    assert "[KUND]" in captured["user"] and "[ADRESS]" in captured["user"]
    assert out == {"category": "Vattenskada", "degraded": False}


def test_assess_maps_unified_scorecard(monkeypatch):
    sc = {"strength_band": "stark", "summary": "ok", "key_factors": ["a"],
          "missing_info": ["b"], "degraded": False, "claim_strength": 80}
    monkeypatch.setattr(intake_ai, "build_scorecard", lambda db, f, **kw: sc)
    out = intake_ai.assess(FIELDS, law_hits=[], arn_hits=[])
    assert out["strength"] == "stark"
    assert out["key_arguments"] == ["a"]
    assert out["missing_info"] == ["b"]
    assert out["scorecard"] is sc
    assert out["degraded"] is False


class AlwaysTakenDB:
    def query(self, *a):
        return self

    def filter(self, *a):
        return self

    def first(self):
        return object()


def test_new_case_id_falls_back_when_pool_exhausted():
    cid = intake_ai._new_case_id(AlwaysTakenDB())
    assert re.fullmatch(r"SC-\d{4}-[0-9a-f]{6}", cid)
