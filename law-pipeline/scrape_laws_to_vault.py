"""
scrape_laws_to_vault.py — Full-scale lagen.nu scraper via Firecrawl.

Fetches complete markdown for all 12 SFS statutes in SFS_MAP,
parses individual paragraphs, and writes them to swiftclaim-obsidian/Lagstiftning/.

Mode A: --full-laws    Write cleaned full-law .md files (one per SFS)
Mode B: --paragraphs    Extract all paragraphs into individual .md files (default)
Mode C: --core-only     Only fill CORE_PARAGRAPHS + existing stubs
"""

from __future__ import annotations

import re
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import httpx
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

console = Console()

VAULT_LAW = Path(__file__).parent.parent / "swiftclaim-obsidian" / "Lagstiftning"
VAULT_LAW.mkdir(parents=True, exist_ok=True)

FIRECRAWL_URL = "http://localhost:3002/v1/scrape"
USER_AGENT = "SwiftclaimLawBot/3.0"

SFS_MAP: dict[str, tuple[str, str]] = {
    "FAL": ("2005:104", "F\u00f6rs\u00e4kringsavtalslagen"),
    "Konsumentf\u00f6rs\u00e4kringslagen": ("1980:38", "Konsumentf\u00f6rs\u00e4kringslag (upph\u00e4vd)"),
    "Trafikskadelagen": ("1975:1410", "Trafikskadelag"),
    "Avtalslagen": ("1915:218", "Lag om avtal och andra r\u00e4ttshandlingar p\u00e5 f\u00f6rm\u00f6genhetsr\u00e4ttens omr\u00e5de"),
    "Distansavtalslagen": ("2005:59", "Lag om distansavtal och avtal utanf\u00f6r aff\u00e4rslokaler"),
    "Konsumentk\u00f6plagen": ("1990:932", "Konsumentk\u00f6plag"),
    "Konsumenttj\u00e4nstlagen": ("1985:716", "Konsumenttj\u00e4nstlag"),
    "Konsumentavtalsvillkorslagen": ("1994:1512", "Lag om avtalsvillkor i konsumentf\u00f6rh\u00e5llanden"),
    "Skadest\u00e5ndslagen": ("1972:207", "Skadest\u00e5ndslag"),
    "Jordabalken": ("1970:994", "Jordabalk"),
    "Bostadsr\u00e4ttslagen": ("1991:614", "Bostadsr\u00e4ttslag"),
    "Paketreselagen": ("2018:1217", "Paketreselag"),
}

# All FAL + Skadest\u00e5ndslagen chapters relevant to property insurance
CORE_PARAGRAPHS: list[tuple[str, Optional[int], str]] = [
    ("FAL", 1, "6"),    ("FAL", 2, "7"),    ("FAL", 2, "8"),
    ("FAL", 4, "1"),    ("FAL", 4, "2"),    ("FAL", 4, "4"),
    ("FAL", 4, "6"),    ("FAL", 4, "8"),    ("FAL", 4, "9"),
    ("FAL", 4, "11"),   ("FAL", 7, "1"),    ("FAL", 7, "2"),
    ("FAL", 7, "9"),
    ("Skadest\u00e5ndslagen", 2, "1"),
    ("Skadest\u00e5ndslagen", 2, "3"),
    ("Avtalslagen", None, "36"),
]

_md_cache: dict[str, str] = {}

def firecrawl_markdown(url: str) -> str:
    if url in _md_cache:
        return _md_cache[url]
    r = httpx.post(
        FIRECRAWL_URL,
        json={"url": url, "formats": ["markdown"]},
        headers={"Authorization": "Bearer local", "Content-Type": "application/json"},
        timeout=180,
    )
    r.raise_for_status()
    data = r.json()
    if not data.get("success"):
        raise RuntimeError(f"Firecrawl failed: {data}")
    md = data["data"]["markdown"]
    _md_cache[url] = md
    return md

# --- Markdown Parsing ---

NBSP = "\u00a0"

def parse_paragraphs_from_md(md: str) -> list[dict]:
    """Parse lagen.nu Firecrawl markdown into chapter+paragraph entries.

    Chapter format (Setext H1):
        1 kap. Title
        ============

    Paragraph format:
        [![[K1]](img)](#K1P1S1 "Permal\u00e4nk...")
        [1 \u00a7](#K1P1S1 "Permal\u00e4nk...")
        \u00a0Text text text...
        1.  list item 1
        2.  list item 2
        [![[S2]](img)](#K1P1S2)  (sub-stycke, keep in same paragraph)
        More text...
    """
    paragraphs: list[dict] = []
    current_chapter: Optional[int] = None
    current_chapter_title = ""
    inside_paragraph = False  # Tracks whether we're collecting paragraph text
    current_para: dict = {}

    lines = md.split("\n")

    for i, line in enumerate(lines):
        ls = line.strip()

        # Detect chapter break — also ends current paragraph
        chap_match = re.match(r"^(\d+)\s*kap\.?\s*(.*)", ls)
        if chap_match and i + 1 < len(lines):
            next_ls = lines[i + 1].strip()
            if re.match(r"^={3,}$", next_ls):
                if inside_paragraph:
                    _finalize_para(current_para, paragraphs)
                    inside_paragraph = False
                current_chapter = int(chap_match.group(1))
                current_chapter_title = chap_match.group(2).strip()
                continue

        # Detect H4 section headers (Kommentar, R\u00e4ttsfall, etc.) — end paragraph
        if inside_paragraph and re.match(r"^####\s+", ls):
            _finalize_para(current_para, paragraphs)
            inside_paragraph = False
            continue

        # Detect Setext H2 (e.g., "Tvingande best\u00e4mmelser\n------") — end paragraph
        if inside_paragraph and re.match(r"^-{3,}$", ls) and i > 0:
            _finalize_para(current_para, paragraphs)
            inside_paragraph = False
            continue

        # Detect next paragraph anchor: [N \u00a7](url) — start new, end current
        para_match = re.match(
            r"^\[(\d+(?:\s*[a-z])?)\s*\u00a7\]\(([^)]+)\)\s*$", ls
        )
        if para_match:
            if inside_paragraph:
                _finalize_para(current_para, paragraphs)
                inside_paragraph = False

            para_num = para_match.group(1).strip()
            para_url = para_match.group(2)

            url_chap = None
            kp_match = re.search(r"#K(\d+)P(\d+[a-z]?)", para_url)
            if kp_match:
                url_chap = int(kp_match.group(1))

            current_para = {
                "chapter": current_chapter or url_chap,
                "chapter_title": current_chapter_title,
                "paragraph": para_num,
                "url": para_url,
                "lines": [],
            }
            inside_paragraph = True
            continue

        # Detect K-anchor image (next paragraph's anchor) — end current paragraph
        if inside_paragraph and re.match(r"^\[!\[K\d+\]", ls):
            # Peek ahead: if next line is another paragraph anchor, this ends the current
            if i + 1 < len(lines) and re.match(r"^\[\d+", lines[i + 1].strip()):
                _finalize_para(current_para, paragraphs)
                inside_paragraph = False
            continue

        # Collect text lines for current paragraph
        if inside_paragraph:
            # Skip anchor images (K and S markers)
            if re.match(r"^\[!\[[KS]", ls):
                continue

            # Skip empty lines if we already have content (structural break)
            if not ls:
                continue

            # Clean the line
            cleaned = line.lstrip(NBSP).strip()
            if cleaned:
                # Convert ordered list item: "1.  text" → "1. text"
                list_match = re.match(r"^(\d+)\.\s{2,}(.+)", cleaned)
                if list_match:
                    cleaned = f"{list_match.group(1)}. {list_match.group(2)}"
                current_para["lines"].append(cleaned)

    # Finalize last paragraph
    if inside_paragraph:
        _finalize_para(current_para, paragraphs)

    return paragraphs


def _finalize_para(para: dict, paragraphs: list[dict]) -> None:
    """Build final paragraph text from collected lines and append if valid."""
    body = " ".join(para.get("lines", []))
    body = clean_body_text(body)

    if body and len(body) >= 20:
        paragraphs.append({
            "chapter": para["chapter"],
            "chapter_title": para.get("chapter_title", ""),
            "paragraph": para["paragraph"],
            "url": para["url"],
            "text": body,
        })


def clean_full_law_md(md: str) -> str:
    """Clean up the full-law markdown: remove nav cruft, tidy headers."""
    lines = md.split("\n")
    cleaned: list[str] = []
    skip_until_content = True

    for i, line in enumerate(lines):
        ls = line.strip()

        # Start at the first H1 (both # and Setext === styles)
        if skip_until_content:
            if re.match(r"^#{1,2}\s+\S", ls):
                skip_until_content = False
            elif re.match(r"^={3,}$", ls) and i > 0:
                skip_until_content = False
                continue  # skip the === underline itself

        if skip_until_content:
            continue

        # Skip navigation anchor images and long compare-line cruft
        if re.match(r"^\[!\[", ls) and "K" in ls and "P" in ls:
            continue
        if ls.startswith("J\u00e4mf\u00f6r med") and len(ls) > 200:
            continue

        cleaned.append(line)

    return "\n".join(cleaned)


def clean_body_text(text: str) -> str:
    """Remove markdown artifacts, HTML remnants, nbsp from law text."""
    # Remove markdown links: [text](url) → text
    text = re.sub(r"\[([^\]]*)\]\([^\)]+\)", r"\1", text)
    # Remove image links
    text = re.sub(r"!\[\S*\]\([^\)]+\)", "", text)
    # Remove NBSP chars
    text = text.replace("\u00a0", " ")
    # Remove HTML-like CSS class remnants from old scrapes
    text = re.sub(r'class="[^"]*"', "", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def render_paragraph_file(short: str, chap: Optional[int], para: str,
                          sfs: str, full_name: str, text: str, source_url: str) -> str:
    cite = f"{short} {chap} kap {para} \u00a7" if chap else f"{short} {para} \u00a7"
    text = clean_body_text(text)
    return f"""---
type: lagrum
statute: "{cite}"
sfs: "{sfs}"
full_name: "{full_name}"
source_url: "{source_url}"
---

# {cite}

{text}

## Relevanta ARN-fall
*(genereras automatiskt via backlinks i Obsidian)*

## K\u00e4lla
- [Lagen.nu: {sfs}](https://lagen.nu/{sfs}#{f'K{chap}P' if chap else 'P'}{para.replace(' ', '')})
- [Riksdagen](https://www.riksdagen.se/sv/dokument-och-lagar/dokument/svensk-forfattningssamling/sfs_{sfs.replace(":", "-")})
"""


def file_safe(name: str) -> str:
    return name.replace("/", "-").replace("\\", "-")


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Scrape lagen.nu laws into Obsidian vault")
    ap.add_argument("--full-laws", action="store_true", help="Write full-law .md files")
    ap.add_argument("--paragraphs", action="store_true", help="Extract all paragraphs")
    ap.add_argument("--core-only", action="store_true", help="Fill only core paragraphs + existing stubs")
    ap.add_argument("--limit", type=int, default=0, help="Limit to N SFS statutes")
    ap.add_argument("--sfs", type=str, default="", help="Comma-separated SFS IDs to scrape (e.g. 2005:104,1915:218)")
    ap.add_argument("--force", action="store_true", help="Overwrite existing paragraph files")
    args = ap.parse_args()

    if not any([args.full_laws, args.paragraphs, args.core_only]):
        args.paragraphs = True
        args.full_laws = True

    # Determine which SFS to process
    if args.sfs:
        target_sfs = args.sfs.split(",")
        sfs_entries = {k: v for k, v in SFS_MAP.items() if v[0] in target_sfs}
    else:
        sfs_entries = dict(SFS_MAP)

    if args.limit:
        sfs_entries = dict(list(sfs_entries.items())[:args.limit])

    console.print(f"[bold]Scraping {len(sfs_entries)} SFS statutes from lagen.nu via Firecrawl[/bold]\n")

    stats = {"laws": 0, "paragraphs": 0, "skipped_existing": 0, "errors": 0}
    all_paragraphs: list[dict] = []

    with Progress(
        SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
        BarColumn(), TextColumn("{task.completed}/{task.total}")
    ) as progress:
        task = progress.add_task("Scraping...", total=len(sfs_entries))

        for short_name, (sfs_id, full_name) in sfs_entries.items():
            try:
                url = f"https://lagen.nu/{sfs_id}"
                console.print(f"  [cyan]Fetching[/cyan] {short_name} ({sfs_id})...")
                md = firecrawl_markdown(url)

                # --- Full law file ---
                if args.full_laws:
                    cleaned = clean_full_law_md(md)
                    law_path = VAULT_LAW / file_safe(f"{full_name} {sfs_id}.md")
                    law_path.write_text(cleaned, encoding="utf-8")
                    stats["laws"] += 1
                    console.print(f"    [green]\u2713[/green] Full law: {law_path.name}")

                # --- Paragraph extraction ---
                if args.paragraphs or args.core_only:
                    paragraphs = parse_paragraphs_from_md(md)
                    all_paragraphs.extend(paragraphs)
                    console.print(f"    [dim]Parsed {len(paragraphs)} paragraphs[/dim]")

                    for p in paragraphs:
                        chap = p["chapter"]
                        para = p["paragraph"]
                        text = p["text"]

                        if not text or len(text) < 20:
                            continue

                        if args.core_only:
                            # Check if this paragraph is in CORE_PARAGRAPHS
                            is_core = any(
                                short_name == c[0] and chap == c[1] and para == c[2]
                                for c in CORE_PARAGRAPHS
                            )
                            if not is_core:
                                continue

                        cite = f"{short_name} {chap} kap {para} \u00a7" if chap else f"{short_name} {para} \u00a7"
                        filename = file_safe(f"{cite}.md")
                        filepath = VAULT_LAW / filename

                        if filepath.exists() and not args.force:
                            stats["skipped_existing"] += 1
                            continue

                        source_url = f"https://lagen.nu/{sfs_id}#{f'K{chap}P' if chap else 'P'}{para.replace(' ', '')}"
                        content = render_paragraph_file(short_name, chap, para, sfs_id, full_name, text, source_url)
                        filepath.write_text(content, encoding="utf-8")
                        stats["paragraphs"] += 1

                progress.update(task, advance=1)
                time.sleep(2)  # Rate limit

            except Exception as e:
                console.print(f"    [red]\u2717[/red] Error: {e}")
                stats["errors"] += 1
                progress.update(task, advance=1)

    # --- Summary ---
    console.print()
    console.print(f"[bold]Done.[/bold]")
    console.print(f"  Full laws written:    {stats['laws']}")
    console.print(f"  Paragraphs written:   {stats['paragraphs']}")
    console.print(f"  Skipped (existing):   {stats['skipped_existing']}")
    console.print(f"  Errors:               {stats['errors']}")
    console.print(f"  Total paragraphs parsed: {len(all_paragraphs)}")

    # Update summary count
    existing_md = sorted(VAULT_LAW.glob("*.md"))
    console.print(f"\n[bold]Vault now contains {len(existing_md)} .md files in Lagstiftning/[/bold]")

    return 0


if __name__ == "__main__":
    sys.exit(main())
