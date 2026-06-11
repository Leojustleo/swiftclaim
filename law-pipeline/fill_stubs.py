"""
fill_stubs.py — Populates law-vault/Lagstiftning/*.md stubs with actual
paragraph text from lagen.nu (which exposes clean #K{chap}P{para} anchors).

MVP scope: only the SFS laws referenced by the first 5 ARN decisions.
Skips stubs whose short-name isn't in SFS_MAP — those can be added later.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import httpx
from rich.console import Console

console = Console()

VAULT_LAW = Path(__file__).parent.parent / "swiftclaim-obsidian" / "Lagstiftning"

# Short-name → SFS ID (extend as new statutes appear in ARN decisions)
SFS_MAP = {
    # Försäkring
    "FAL":                           ("2005:104", "Försäkringsavtalslagen"),
    "Försäkringsavtalslagen":        ("2005:104", "Försäkringsavtalslagen"),
    "Konsumentförsäkringslagen":     ("1980:38",  "Konsumentförsäkringslag (upphävd, ersatt av FAL)"),
    "Trafikskadelagen":              ("1975:1410", "Trafikskadelag"),
    # Avtal & konsument
    "Avtalslagen":                   ("1915:218", "Lag om avtal och andra rättshandlingar på förmögenhetsrättens område"),
    "Distansavtalslagen":            ("2005:59",  "Lag om distansavtal och avtal utanför affärslokaler"),
    # 1990:932 is the version cited by ARN decisions 2018-2022 (in force until 2022-05).
    # New cases may cite SFS 2022:260; revisit when scaling past the MVP test set.
    "Konsumentköplagen":             ("1990:932", "Konsumentköplag (äldre, gäller köp t.o.m. 2022-04-30)"),
    "Konsumenttjänstlagen":          ("1985:716", "Konsumenttjänstlag"),
    "Konsumentavtalsvillkorslagen":  ("1994:1512", "Lag om avtalsvillkor i konsumentförhållanden"),
    # Skadestånd & egendom
    "Skadeståndslagen":              ("1972:207", "Skadeståndslag"),
    "Jordabalken":                   ("1970:994", "Jordabalk"),
    "JB":                            ("1970:994", "Jordabalk"),
    "Bostadsrättslagen":             ("1991:614", "Bostadsrättslag"),
    "Hyreslagen":                    ("1970:994", "Hyreslag (JB 12 kap)"),
    # Resa
    "Paketreselagen":                ("2018:1217", "Paketreselag"),
    "Paketresor":                    ("2018:1217", "Paketreselag"),
}

# Core property-insurance paragraphs Swiftclaim will rely on regardless of which
# ARN decisions happen to be in the vault. Seeded into Lagstiftning/ on every run.
CORE_PARAGRAPHS: list[tuple[str, str | None, str]] = [
    # FAL — Försäkringsavtalslagen 2005:104
    ("FAL", "1", "6"),    # Tvingande regler
    ("FAL", "2", "7"),    # Information vid teckning
    ("FAL", "2", "8"),    # Framhållande av viktiga säkerhetsföreskrifter
    ("FAL", "4", "1"),    # Oriktiga uppgifter vid teckning
    ("FAL", "4", "2"),    # Förändring av risk
    ("FAL", "4", "4"),    # Framkallande av försäkringsfallet
    ("FAL", "4", "6"),    # Säkerhetsföreskrift
    ("FAL", "4", "8"),    # Räddningsplikt
    ("FAL", "4", "9"),    # Räddningskostnader
    ("FAL", "4", "11"),   # Förbud mot säkerhetsföreskrift förklädd som omfattningsvillkor
    ("FAL", "7", "1"),    # Skadereglering — skyndsamhet
    ("FAL", "7", "2"),    # Tid för utbetalning
    ("FAL", "7", "9"),    # Påföljd vid dröjsmål
    # Skadeståndslagen 1972:207
    ("Skadeståndslagen", "2", "1"),  # Sak- och personskada
    ("Skadeståndslagen", "2", "3"),  # Ren förmögenhetsskada
    # Avtalslagen — generalklausulen
    ("Avtalslagen", None, "36"),
]


def ensure_core_stubs(stubs: list[Path]) -> list[Path]:
    """Create empty stub files for any CORE_PARAGRAPHS not yet present, return updated list."""
    existing = {p.name for p in stubs}
    added: list[Path] = []
    for short, chap, para in CORE_PARAGRAPHS:
        name = f"{short} {chap} kap {para} §.md" if chap else f"{short} {para} §.md"
        if name in existing:
            continue
        path = VAULT_LAW / name
        path.write_text(f"---\ntype: lagrum\nstatute: \"{name[:-3]}\"\n---\n")
        added.append(path)
    if added:
        console.print(f"[cyan]Seeded {len(added)} core statute stubs[/cyan]")
    return sorted(stubs + added)


# "FAL 4 kap 6 §" / "Avtalslagen 36 §" / "Konsumentköplagen 16 § tredje stycket 2"
STUB_RE = re.compile(
    r"^(?P<short>[A-Za-zåäöÅÄÖ]+)"
    r"(?:\s+(?P<chap>\d+)\s*kap)?"
    r"\s+(?P<para>\d+(?:\s*[a-z])?)\s*§"
)

_html_cache: dict[str, str] = {}


def fetch_law_html(sfs: str) -> str:
    if sfs in _html_cache:
        return _html_cache[sfs]
    url = f"https://lagen.nu/{sfs}"
    r = httpx.get(url, timeout=30, follow_redirects=True,
                  headers={"User-Agent": "LegalResearchBot/1.0 (Swiftclaim)"})
    r.raise_for_status()
    _html_cache[sfs] = r.text
    return r.text


def extract_paragraph(law_html: str, chap: str | None, para: str) -> str | None:
    """Find the #K{chap}P{para} or #P{para} block and return its plain text."""
    para_clean = para.replace(" ", "").lower()  # "3 a" → "3a" — lagen.nu uses no space
    anchor = f"K{chap}P{para_clean}" if chap else f"P{para_clean}"

    # Try exact anchor, then fall back to base paragraph (drop letter suffix)
    candidates = [anchor]
    if re.search(r"[a-z]$", para_clean):
        base = re.sub(r"[a-z]+$", "", para_clean)
        candidates.append(f"K{chap}P{base}" if chap else f"P{base}")

    for candidate in candidates:
        m = re.search(rf'id="{candidate}"', law_html)
        if not m:
            continue
        # Grab from this anchor until the next K*P* anchor (or end)
        rest = law_html[m.end():]
        end_match = re.search(r'id="K?\d+P?\d+[a-z]?"', rest)
        block = rest[:end_match.start()] if end_match else rest[:5000]
        # Strip HTML tags
        text = re.sub(r"<[^>]+>", " ", block)
        # Collapse whitespace
        text = re.sub(r"\s+", " ", text).strip()
        return text or None
    return None


def render_filled_stub(short: str, chap: str | None, para: str, sfs: str,
                       full_name: str, text: str) -> str:
    cite = f"{short} {chap} kap {para} §" if chap else f"{short} {para} §"
    return f"""---
type: lagrum
statute: "{cite}"
sfs: "{sfs}"
full_name: "{full_name}"
source_url: "https://lagen.nu/{sfs}"
---

# {cite}

{text}

## Relevanta ARN-fall
*(genereras automatiskt via backlinks i Obsidian)*

## Källa
- [Lagen.nu: {sfs}](https://lagen.nu/{sfs})
- [Riksdagen](https://www.riksdagen.se/sv/dokument-och-lagar/dokument/svensk-forfattningssamling/sfs_{sfs.replace(":", "-")})
"""


def main() -> int:
    if not VAULT_LAW.exists():
        console.print(f"[red]No vault at {VAULT_LAW} — run main.py first[/red]")
        return 1

    stubs = sorted(VAULT_LAW.glob("*.md"))
    stubs = ensure_core_stubs(stubs)
    filled = 0
    skipped_unmapped = 0
    skipped_no_para = 0
    failed_lookup = 0

    for path in stubs:
        name = path.stem
        m = STUB_RE.match(name)
        if not m:
            skipped_no_para += 1
            console.print(f"[dim]· skip (no paragraph reference): {name}[/dim]")
            continue

        short = m.group("short")
        chap  = m.group("chap")
        para  = m.group("para").strip()

        if short not in SFS_MAP:
            skipped_unmapped += 1
            console.print(f"[yellow]· skip (unmapped statute {short!r}): {name}[/yellow]")
            continue

        sfs, full_name = SFS_MAP[short]
        try:
            law_html = fetch_law_html(sfs)
        except Exception as e:
            console.print(f"[red]✗ fetch failed for {sfs}: {e}[/red]")
            failed_lookup += 1
            continue

        text = extract_paragraph(law_html, chap, para)
        if not text:
            failed_lookup += 1
            console.print(f"[red]✗ anchor not found: {name}[/red]")
            continue

        path.write_text(render_filled_stub(short, chap, para, sfs, full_name, text))
        filled += 1
        console.print(f"[green]✓ filled: {name} ({len(text)} chars)[/green]")

    console.print()
    console.print(f"[bold]Done.[/bold] filled={filled}  skipped_unmapped={skipped_unmapped}  "
                  f"skipped_no_paragraph={skipped_no_para}  failed_lookup={failed_lookup}  "
                  f"total_stubs={len(stubs)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
