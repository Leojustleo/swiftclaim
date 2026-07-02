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


def test_assess_scrubs_pii(monkeypatch):
    captured = {}

    def fake_chat(system, user, schema, **kw):
        captured["user"] = user
        return schema(strength="stark", summary="ok"), {"model": "m"}

    monkeypatch.setattr(intake_ai, "chat_json", fake_chat)
    fields = dict(
        FIELDS,
        damage_category="Vattenskada",
        damage_description="Läcka hos Anna Andersson, Storgatan 1, Lund",
        insurer_reason="Anna Andersson anmälde för sent",
    )
    out = intake_ai.assess(fields, law_hits=[], arn_hits=[])
    assert "Anna" not in captured["user"]
    assert "[KUND]" in captured["user"]
    assert out["strength"] == "stark"
    assert out["degraded"] is False
