from app.rag import DIR_MAP, MAX_NOTE_CHARS, eligible_notes, note_source_url


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
    assert len(all_dirs) == 2  # full law dropped, Koncept never searched
    only_arn = eligible_notes(notes, dirs=["arn"])
    assert [n["path"] for n in only_arn] == ["ARN/ARN 2023-001"]


def test_note_source_url():
    text = '---\ntype: lagrum\nsource_url: "https://lagen.nu/2005:104#K4P6"\n---\n\n# FAL'
    assert note_source_url(text) == "https://lagen.nu/2005:104#K4P6"
    assert note_source_url("# No frontmatter") is None
