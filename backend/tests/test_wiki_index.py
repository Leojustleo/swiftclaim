from app.wiki_index import build_index, get_index, get_decision_text


def test_build_index_returns_string():
    index = build_index()
    assert isinstance(index, str)
    assert "# ARN Wiki Index" in index


def test_index_contains_arn_decisions():
    index = build_index()
    assert index.count("## ARN") >= 10


def test_index_contains_expected_fields():
    index = build_index()
    assert "Utfall:" in index
    assert "Bolag:" in index
    assert "Nyckelord:" in index


def test_get_index_uses_cache():
    index1 = get_index()
    index2 = get_index()
    assert index1 == index2


def test_get_decision_text_found():
    text = get_decision_text("2018-11707")
    assert "ARN" in text
    assert len(text) > 100


def test_get_decision_text_not_found():
    text = get_decision_text("9999-99999")
    assert text == ""
