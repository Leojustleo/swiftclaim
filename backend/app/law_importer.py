from __future__ import annotations

import re
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple, Dict

import httpx

USER_AGENT = "LegalResearchBot/2.0 (Swiftclaim - property insurance research)"
FIRECRAWL_URL = "http://localhost:3002/v1/scrape"


@dataclass
class LawSection:
    statute_name: str
    sfs_id: str
    full_name: str
    chapter: Optional[int]
    paragraph: str
    full_reference: str
    body_html: str
    body_text: str
    source_url: str


SFS_MAP: dict[str, tuple[str, str]] = {
    "FAL": ("2005:104", u"F\u00f6rs\u00e4kringsavtalslagen"),
    u"F\u00f6rs\u00e4kringsavtalslagen": ("2005:104", u"F\u00f6rs\u00e4kringsavtalslagen"),
    u"Konsumentf\u00f6rs\u00e4kringslagen": ("1980:38", u"Konsumentf\u00f6rs\u00e4kringslag (upph\u00e4vd, ersatt av FAL)"),
    "Trafikskadelagen": ("1975:1410", "Trafikskadelag"),
    "Avtalslagen": ("1915:218", u"Lag om avtal och andra r\u00e4ttshandlingar p\u00e5 f\u00f6rm\u00f6genhetsr\u00e4ttens omr\u00e5de"),
    "Distansavtalslagen": ("2005:59", "Lag om distansavtal och avtal utanf\u00f6r aff\u00e4rslokaler"),
    u"Konsumentk\u00f6plagen": ("1990:932", u"Konsumentk\u00f6plag (\u00e4ldre, g\u00e4ller k\u00f6p t.o.m. 2022-04-30)"),
    u"Konsumenttj\u00e4nstlagen": ("1985:716", u"Konsumenttj\u00e4nstlag"),
    "Konsumentavtalsvillkorslagen": ("1994:1512", "Lag om avtalsvillkor i konsumentf\u00f6rh\u00e5llanden"),
    u"Skadest\u00e5ndslagen": ("1972:207", u"Skadest\u00e5ndslag"),
    "Jordabalken": ("1970:994", "Jordabalk"),
    "JB": ("1970:994", "Jordabalk"),
    u"Bostadsr\u00e4ttslagen": ("1991:614", u"Bostadsr\u00e4ttslag"),
    "Paketreselagen": ("2018:1217", "Paketreselag"),
}

PARAGRAPH_RE = re.compile(
    r"^(?P<short>[A-Za-z\u00e5\u00e4\u00f6\u00c5\u00c4\u00d6]+)"
    r"(?:\s+(?P<chap>\d+)\s*kap)?"
    r"\s+(?P<para>\d+(?:\s*[a-z])?)\s*\u00a7"
)

# Cache for Firecrawl scrapes to avoid re-fetching
_markdown_cache: Dict[str, str] = {}


def _firecrawl_scrape(url: str) -> str:
    """Scrape lagen.nu URL via Firecrawl MCP, return clean markdown."""
    if url in _markdown_cache:
        return _markdown_cache[url]
    r = httpx.post(
        FIRECRAWL_URL,
        json={"url": url, "formats": ["markdown"]},
        headers={
            "Authorization": "Bearer local",
            "Content-Type": "application/json",
        },
        timeout=120,
    )
    r.raise_for_status()
    data = r.json()
    if not data.get("success"):
        raise RuntimeError(f"Firecrawl failed: {data}")
    md = data["data"]["markdown"]
    _markdown_cache[url] = md
    return md


def parse_reference(reference: str) -> Optional[dict]:
    m = PARAGRAPH_RE.match(reference)
    if not m:
        return None
    chap = int(m.group("chap")) if m.group("chap") else None
    return {"short": m.group("short"), "chap": chap, "para": m.group("para").strip()}


def resolve_sfs(statute_name: str) -> Optional[tuple[str, str]]:
    return SFS_MAP.get(statute_name)


def _extract_paragraph_from_markdown(md: str, chapter: Optional[int], paragraph: str) -> tuple[str, str]:
    para_clean = paragraph.strip().lower()
    anchor_base = f"K{chapter}P{para_clean}" if chapter else f"P{para_clean}"

    lines = md.split("\n")
    start_idx = None
    for i, line in enumerate(lines):
        if f"#{anchor_base}S1\"" in line or f"#{anchor_base}S1 " in line:
            for j in range(i, min(i + 3, len(lines))):
                cleaned = re.sub(r'\[([^\]]*)\]\([^\)]+\)', r'\1', lines[j]).strip()
                cleaned_no_space = cleaned.replace(" ", "")
                expected = f"{paragraph}\u00a7"
                if cleaned_no_space.startswith(expected):
                    start_idx = i
                    break
            if start_idx is not None:
                break

    if start_idx is None:
        return "", ""

    collected: list[str] = []
    for i in range(start_idx, len(lines)):
        line = lines[i]
        cleaned = line.strip()
        # Remove all markdown links: [anything](url) — both image and text
        cleaned = re.sub(r'\[!?(?:\[[^\]]*\])+\]?\([^\)]+\)', '', cleaned)
        cleaned = re.sub(r'\[([^\]]*)\]\([^\)]+\)', r'\1', cleaned)
        cleaned = cleaned.strip()
        cs = cleaned.replace(" ", "")

        if i > start_idx + 2 and cleaned:
            if re.match(r'^\d+[a-z]?\s*\u00a7', cleaned):
                break
            if re.search(rf'#K\d+P\d+S1', line):
                break
        if re.match(r'^####\s+', cleaned):
            break
        if cleaned:
            collected.append(cleaned)

    body_text = " ".join(collected).strip()
    body_text = re.sub(r'\s+', ' ', body_text)
    return body_text, body_text


def get_law_section(reference: str) -> Optional[LawSection]:
    parsed = parse_reference(reference)
    if not parsed:
        return None

    sfs_info = resolve_sfs(parsed["short"])
    if not sfs_info:
        return None

    sfs_id, full_name = sfs_info
    full_ref = f"{parsed['short']} {parsed['chap']} kap {parsed['para']} \u00a7" if parsed["chap"] else f"{parsed['short']} {parsed['para']} \u00a7"

    try:
        url = f"https://lagen.nu/{sfs_id}"
        md = _firecrawl_scrape(url)
        body_html, body_text = _extract_paragraph_from_markdown(md, parsed["chap"], parsed["para"])
        if not body_text:
            return None
    except Exception:
        return None

    return LawSection(
        statute_name=parsed["short"],
        sfs_id=sfs_id,
        full_name=full_name,
        chapter=parsed["chap"],
        paragraph=parsed["para"],
        full_reference=full_ref,
        body_html=body_html,
        body_text=body_text,
        source_url=f"https://lagen.nu/{sfs_id}#K{parsed['chap']}P{parsed['para']}"
        if parsed["chap"]
        else f"https://lagen.nu/{sfs_id}#P{parsed['para']}",
    )


def get_full_law_markdown(sfs_id: str) -> str:
    """Fetch and return the full cleaned markdown of a statute from lagen.nu via Firecrawl."""
    url = f"https://lagen.nu/{sfs_id}"
    return _firecrawl_scrape(url)


def get_law_markdown_by_chapter(sfs_id: str, chapter: int) -> str:
    """Fetch full law and return only the given chapter's markdown."""
    md = _firecrawl_scrape(f"https://lagen.nu/{sfs_id}")
    lines = md.split("\n")
    chap_pattern = re.compile(rf"^##\s+{chapter}\s+kap\.?", re.IGNORECASE)
    collected: list[str] = []
    in_chapter = False

    for i, line in enumerate(lines):
        if chap_pattern.match(line):
            in_chapter = True
            collected.append(line)
            continue
        if in_chapter:
            if re.match(r"^##\s+\d+\s+kap\.?", line, re.IGNORECASE):
                break
            collected.append(line)

    return "\n".join(collected)


# ── Riksdagen API ────────────────────────────────────────────────────────

RIKSDAGEN_BASE = "https://data.riksdagen.se"

RIKSDAGEN_SFS_DOCS: dict[str, str] = {
    "2005:104": "sfs-2005-104",
    "1972:207": "sfs-1972-207",
    "1915:218": "sfs-1915-218",
    "2005:59": "sfs-2005-59",
    "1990:932": "sfs-1990-932",
    "1985:716": "sfs-1985-716",
    "1991:614": "sfs-1991-614",
    "1970:994": "sfs-1970-994",
    "2018:1217": "sfs-2018-1217",
}


def fetch_riksdagen_law(sfs_id: str) -> Optional[dict]:
    doc_id = RIKSDAGEN_SFS_DOCS.get(sfs_id)
    if not doc_id:
        doc_id = f"sfs-{sfs_id.replace(':', '-')}"

    try:
        r = httpx.get(
            f"{RIKSDAGEN_BASE}/dokument/{doc_id}.json",
            timeout=30,
            headers={"User-Agent": USER_AGENT},
            params={"utformat": "json"},
        )
        if r.status_code != 200:
            return None
        meta = r.json().get("dokumentstatus", {}).get("dokument", {})
        # Use Firecrawl for riksdagen.se too
        md = _firecrawl_scrape(f"https://www.riksdagen.se/sv/dokument-och-lagar/dokument/svensk-forfattningssamling/{doc_id}_sfs-{sfs_id.replace(':', '-')}/")
        return {
            "sfs_id": sfs_id,
            "title": meta.get("titel", ""),
            "published": meta.get("publiceringsdatum", ""),
            "markdown": md,
            "source": f"https://www.riksdagen.se/sv/dokument-och-lagar/dokument/svensk-forfattningssamling/{doc_id}_sfs-{sfs_id.replace(':', '-')}/",
        }
    except Exception:
        return None


CORE_SECTIONS: list[tuple[str, Optional[int], str]] = [
    ("FAL", 1, "6"),
    ("FAL", 2, "7"),
    ("FAL", 2, "8"),
    ("FAL", 4, "1"),
    ("FAL", 4, "2"),
    ("FAL", 4, "4"),
    ("FAL", 4, "6"),
    ("FAL", 4, "8"),
    ("FAL", 4, "9"),
    ("FAL", 4, "11"),
    ("FAL", 7, "1"),
    ("FAL", 7, "2"),
    ("FAL", 7, "9"),
    ("Skadest\u00e5ndslagen", 2, "1"),
    ("Avtalslagen", None, "36"),
]