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


def test_precedent_query_scrubbed(monkeypatch):
    captured = {}

    def fake_precedents(category, text, k=5):
        captured["text"] = text
        return []

    monkeypatch.setattr(intake_ai, "search_precedents", fake_precedents)
    monkeypatch.setattr(intake_ai, "search_law", lambda q, k=8: [])
    monkeypatch.setattr(intake_ai, "chat_json", lambda *a, **kw: (_ for _ in ()).throw(intake_ai.LLMError("off")))

    class NoCaseDB:
        def query(self, *a):
            return self

        def filter(self, *a):
            return self

        def first(self):
            return None

        def add(self, obj):
            pass

        def commit(self):
            pass

        def refresh(self, obj):
            pass

    payload = dict(FIELDS, damage_description="Läcka hos Anna Andersson", insurer_reason="Anna Andersson anmälde för sent")
    intake_ai.analyze(payload, NoCaseDB())
    assert "Anna" not in captured["text"]
