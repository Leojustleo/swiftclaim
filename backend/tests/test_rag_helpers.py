from app import rag
from app.rag import (
    DIR_MAP, LEXICAL_MAX_BOOST, MAX_NOTE_CHARS,
    eligible_notes, idf_weights, lexical_boost, note_source_url, query_terms,
)


def _note(path, chars=100):
    return {"path": path, "title": path, "text": "x" * chars}


def test_eligible_notes_filters_dirs_and_size():
    notes = [
        _note("Lagstiftning/FAL 4 kap 6 §"),
        _note("Lagstiftning/FAL hela lagen", chars=MAX_NOTE_CHARS + 1),
        _note("ARN/ARN 2023-001"),
        _note("Koncept/Nedsättning"),
    ]
    all_dirs = eligible_notes(notes)
    assert len(all_dirs) == 3  # full law dropped by size; all top-level dirs searchable
    only_arn = eligible_notes(notes, dirs=["arn"])
    assert [n["path"] for n in only_arn] == ["ARN/ARN 2023-001"]


def test_eligible_notes_includes_new_top_level_dir():
    notes = [
        _note("Domar/NJA 2020 s 1.md"),
        _note("Index/allt.md"),
        _note("rot.md"),
    ]
    got = eligible_notes(notes)
    assert [n["path"] for n in got] == ["Domar/NJA 2020 s 1.md"]


def test_eligible_notes_alias_and_literal_dirs():
    notes = [
        _note("ARN/ARN 2020-1.md"),
        _note("Domar/dom.md"),
    ]
    assert [n["path"] for n in eligible_notes(notes, dirs=["arn"])] == ["ARN/ARN 2020-1.md"]
    assert [n["path"] for n in eligible_notes(notes, dirs=["Domar"])] == ["Domar/dom.md"]


def test_reindex_vault_embeds_only_new_files(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    (vault / "Domar").mkdir(parents=True)
    (vault / "Domar" / "a.md").write_text("innehåll om vattenskada och åldersavdrag " * 4)
    monkeypatch.setattr(rag, "EMBED_CACHE", tmp_path / "emb.json")
    monkeypatch.setattr(rag, "voyage_embed",
                        lambda texts, key, input_type, **kw: [[0.1] * 4 for _ in texts])
    monkeypatch.setattr(rag, "_get_voyage_key", lambda: "k")

    assert rag.reindex_vault(vault) == {"total_notes": 1, "embedded": 1}
    assert rag.reindex_vault(vault) == {"total_notes": 1, "embedded": 0}


def test_note_source_url():
    text = '---\ntype: lagrum\nsource_url: "https://lagen.nu/2005:104#K4P6"\n---\n\n# FAL'
    assert note_source_url(text) == "https://lagen.nu/2005:104#K4P6"
    assert note_source_url("# No frontmatter") is None


def test_query_terms_drops_short_and_stopwords():
    terms = query_terms("När får bolaget göra åldersavdrag på ersättningen?")
    assert "åldersavdrag" in terms and "ersättningen" in terms
    assert "när" not in terms and "får" not in terms and "göra" not in terms


def test_lexical_boost_bounded_and_proportional():
    terms = ["åldersavdrag", "ersättningen"]
    full = lexical_boost(terms, "bolaget gör åldersavdrag på ersättningen enligt tabell")
    half = lexical_boost(terms, "åldersavdrag regleras i villkoren")
    none = lexical_boost(terms, "jordabalken handlar om fastigheter")
    assert full == LEXICAL_MAX_BOOST
    assert 0 < half < full
    assert none == 0.0
    assert lexical_boost([], "text") == 0.0


def test_idf_rare_term_dominates_boost():
    # "ersättning" in every doc (no signal), "åldersavdrag" in one doc (strong signal)
    pool = ["ersättning för skada", "ersättning vid brand", "åldersavdrag på ersättning"]
    terms = ["åldersavdrag", "ersättning"]
    weights = idf_weights(terms, pool)
    assert weights["åldersavdrag"] > weights["ersättning"]
    rare_only = lexical_boost(terms, "tabell för åldersavdrag", weights)
    common_only = lexical_boost(terms, "ersättning utbetalas", weights)
    assert rare_only > common_only
