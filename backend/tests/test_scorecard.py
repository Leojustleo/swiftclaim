from app import scorecard

FIELDS = {
    "customer_name": "Anna Andersson",
    "customer_email": "anna@example.se",
    "customer_phone": "0701234567",
    "property_address": "Storgatan 1, Lund",
    "insurance_policy_number": "HF-99887766",
    "damage_category": "Vattenskada",
    "damage_description": "Läcka hos Anna Andersson, Storgatan 1, Lund",
    "insurance_company": "Folksam",
    "claim_amount": 180000,
    "insurer_decision": "partial",
    "insurer_amount": 72000,
    "insurer_reason": "Åldersavdrag enligt tabell",
}


def test_band_and_priority_derivation():
    assert scorecard.band_from_strength(85) == "stark"
    assert scorecard.band_from_strength(70) == "stark"
    assert scorecard.band_from_strength(69) == "medel"
    assert scorecard.band_from_strength(40) == "medel"
    assert scorecard.band_from_strength(39) == "svag"
    assert scorecard.band_from_strength(None) == "okänd"
    assert scorecard.priority_from_strength(70) == "high"
    assert scorecard.priority_from_strength(40) == "medium"
    assert scorecard.priority_from_strength(10) == "low"
    assert scorecard.priority_from_strength(None) == "unknown"


class FakeResolver:
    def resolve(self, ref):
        if "4 kap 6" in ref:
            return {"ref": "FAL 4 kap 6 §", "kind": "lagrum"}
        if "2020-08495" in ref:
            return {"ref": "ARN 2020-08495", "kind": "arn"}
        return None


def test_build_scorecard_scrubs_pii_and_flags_bad_refs(monkeypatch):
    captured = {}

    def fake_chat(system, user, schema, **kw):
        captured["user"] = user
        return schema(
            claim_strength=72, win_probability="65%", summary="Bra läge.",
            key_factors=["Åldersavdrag över villkorstabellen"],
            recommended_action="Bestrid med hänvisning till FAL.",
            missing_info=[],
            arn_references=["2020-08495", "1999-99999"],
            lagrum_references=["FAL 4 kap 6 §"],
        ), {"model": "m"}

    monkeypatch.setattr(scorecard, "chat_json", fake_chat)
    monkeypatch.setattr(scorecard, "build_resolver", lambda db, ev: FakeResolver())

    sc = scorecard.build_scorecard(None, FIELDS, law_hits=[], arn_hits=[])

    assert "Anna" not in captured["user"]
    assert "Storgatan" not in captured["user"]
    assert "[KUND]" in captured["user"]
    assert sc["claim_strength"] == 72
    assert sc["strength_band"] == "stark"
    assert sc["priority"] == "high"
    assert sc["arn_references"] == ["ARN 2020-08495"]
    assert sc["lagrum_references"] == ["FAL 4 kap 6 §"]
    assert sc["flagged_references"] == ["1999-99999"]
    assert sc["degraded"] is False


def test_build_scorecard_degrades_on_llm_failure(monkeypatch):
    def boom(*a, **kw):
        raise scorecard.LLMError("down")

    monkeypatch.setattr(scorecard, "chat_json", boom)
    sc = scorecard.build_scorecard(None, FIELDS, law_hits=[], arn_hits=[])
    assert sc["degraded"] is True
    assert sc["claim_strength"] is None
    assert sc["strength_band"] == "okänd"
    assert sc["priority"] == "unknown"


def test_build_scorecard_flags_all_refs_when_resolver_unavailable(monkeypatch):
    def fake_chat(system, user, schema, **kw):
        return schema(
            claim_strength=50, win_probability="50%", summary="s",
            key_factors=[], recommended_action="", missing_info=[],
            arn_references=["2020-08495"], lagrum_references=["FAL 4 kap 6 §"],
        ), {"model": "m"}

    def broken_resolver(db, ev):
        raise RuntimeError("no index")

    monkeypatch.setattr(scorecard, "chat_json", fake_chat)
    monkeypatch.setattr(scorecard, "build_resolver", broken_resolver)
    sc = scorecard.build_scorecard(None, FIELDS, law_hits=[], arn_hits=[])
    assert sc["arn_references"] == []
    assert sc["lagrum_references"] == []
    assert set(sc["flagged_references"]) == {"2020-08495", "FAL 4 kap 6 §"}


def test_parse_probability():
    assert scorecard.parse_probability("65%") == 65
    assert scorecard.parse_probability("ca 70 procent") == 70
    assert scorecard.parse_probability(None) is None
    assert scorecard.parse_probability("") is None


def test_calibration_buckets():
    rows = [
        ("65%", "won"), ("70%", "lost"), ("30%", "lost"),
        ("90%", "partial"), (None, "won"), ("50%", "withdrawn"),
    ]
    out = scorecard.calibration_buckets(rows)
    assert out["60-79"] == {"n": 2, "wins": 1}
    assert out["0-39"] == {"n": 1, "wins": 0}
    assert out["80-100"] == {"n": 1, "wins": 1}
    assert out["40-59"] == {"n": 0, "wins": 0}
