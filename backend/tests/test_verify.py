from app.verify import CitationResolver, normalize_lagrum, verify_citations


def test_normalize_forms():
    assert normalize_lagrum("FAL 4 kap 6 §") == "FAL 4 kap 6 §"
    assert normalize_lagrum("4 kap. 6 § FAL") == "FAL 4 kap 6 §"
    assert normalize_lagrum("36 § avtalslagen (1915:218)") == "Avtalslagen 36 §"
    assert normalize_lagrum("12 kap 18a § JB") == "Jordabalken 12 kap 18 a §"
    assert normalize_lagrum("enligt försäkringsavtalslagen 8 kap 9 §") == "FAL 8 kap 9 §"
    assert normalize_lagrum("Okänd lag 3 §") is None
    assert normalize_lagrum("") is None


def _resolver():
    return CitationResolver(
        vault_titles={"FAL 4 kap 6 §", "Avtalslagen 36 §"},
        law_refs={"FAL 6 kap 1 §"},
        arn_ids={"2018-11707"},
        evidence_ids={"DOC-1", "DOC-2"},
    )


def test_resolver_paths():
    r = _resolver()
    assert r.resolve("doc-2")["kind"] == "evidence"
    assert r.resolve("ARN 2018-11707")["ref"] == "ARN 2018-11707"
    assert r.resolve("4 kap. 6 § FAL")["ref"] == "FAL 4 kap 6 §"
    assert r.resolve("FAL 6 kap 1 §")["kind"] == "lagrum"
    assert r.resolve("ARN 1999-00000") is None
    assert r.resolve("Hittepålagen 99 §") is None


def test_verify_citations_split():
    r = _resolver()
    citations = [
        {"ref": "FAL 4 kap 6 §", "doc_id": "DOC-1"},
        {"ref": "Påhittad lag 1 §", "doc_id": None},
    ]
    verified, flagged = verify_citations(citations, r)
    assert [v["ref"] for v in verified] == ["FAL 4 kap 6 §"]
    assert flagged == ["Påhittad lag 1 §"]
