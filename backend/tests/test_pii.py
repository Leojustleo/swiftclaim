from app.llm import scrub_pii, unscrub_pii

FIELDS = {
    "customer_name": "Anna Andersson",
    "customer_email": "anna@example.se",
    "customer_phone": "0701234567",
    "property_address": "Storgatan 1, Lund",
    "insurance_policy_number": "HF-99887766",
}


def test_scrub_replaces_all_pii():
    text = "Anna Andersson (anna@example.se, 0701234567) bor på Storgatan 1, Lund."
    out = scrub_pii(text, FIELDS)
    assert "Anna" not in out and "anna@" not in out and "070" not in out and "Storgatan" not in out
    assert "[KUND]" in out and "[EPOST]" in out and "[TELEFON]" in out and "[ADRESS]" in out


def test_round_trip():
    text = "Kund Anna Andersson kräver ersättning."
    assert unscrub_pii(scrub_pii(text, FIELDS), FIELDS) == text


def test_short_values_not_replaced():
    fields = {"customer_name": "AB", "customer_email": "", "customer_phone": "", "property_address": ""}
    assert scrub_pii("AB är ett vanligt ord", fields) == "AB är ett vanligt ord"


def test_scrub_replaces_policy_number():
    text = "Försäkringsnummer: HF-99887766 hos Folksam."
    out = scrub_pii(text, FIELDS)
    assert "HF-99887766" not in out
    assert "[FÖRSNR]" in out
    assert unscrub_pii(out, FIELDS) == text
