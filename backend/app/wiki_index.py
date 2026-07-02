from __future__ import annotations
import re
from pathlib import Path

import yaml

VAULT_ARN = Path(__file__).parent.parent.parent / "swiftclaim-obsidian" / "ARN"
INDEX_PATH = Path(__file__).parent.parent / "data" / "arn_wiki_index.md"


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    try:
        end = text.index("---", 3)
    except ValueError:
        return {}, text
    raw = text[3:end]
    body = text[end + 3:].strip()
    try:
        fm = yaml.safe_load(raw) or {}
    except yaml.YAMLError:
        # Fall back to a forgiving line-by-line regex parse
        fm = {}
        for line in raw.splitlines():
            m = re.match(r'^(\w+):\s*(.*)', line)
            if m:
                key, val = m.group(1), m.group(2).strip().strip('"\'')
                if key not in fm:
                    fm[key] = val
    return fm, body


def _extract_summary(body: str, max_chars: int = 350) -> str:
    match = re.search(r"## ARN:s bedömning\s+(.+?)(?=\n##|\Z)", body, re.DOTALL)
    text = (match.group(1) if match else body).strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0] + "..."


def build_index() -> str:
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    files = sorted(VAULT_ARN.glob("*.md"))
    lines = [f"# ARN Wiki Index — {len(files)} beslut\n"]

    for f in files:
        text = f.read_text(encoding="utf-8")
        fm, body = _parse_frontmatter(text)
        case_id = str(fm.get("case_id", f.stem.replace("ARN ", "")))
        lines.append(f"## ARN {case_id}")
        category = fm.get("category", "—")
        damage = fm.get("damage_type", "—")
        lines.append(f"- Kategori: {category} / {damage}")
        lines.append(f"- Utfall: {fm.get('outcome', '—')}")
        lines.append(f"- Bolag: {fm.get('insurer', '—')}")
        amount = fm.get("claim_amount_sek")
        if amount:
            lines.append(f"- Belopp: {int(amount):,} kr".replace(",", " "))
        legal = fm.get("legal_basis") or []
        if legal:
            lines.append(f"- Rättslig grund: {', '.join(str(x) for x in legal[:3])}")
        keywords = fm.get("keywords") or []
        if keywords:
            lines.append(f"- Nyckelord: {', '.join(str(x) for x in keywords[:5])}")
        summary = _extract_summary(body)
        lines.append(f"- Sammanfattning: {summary}")
        lines.append("")

    content = "\n".join(lines)
    INDEX_PATH.write_text(content, encoding="utf-8")
    return content


def get_index() -> str:
    if INDEX_PATH.exists():
        return INDEX_PATH.read_text(encoding="utf-8")
    return build_index()


def get_decision_text(arn_id: str) -> str:
    """Return full markdown text of a decision by its ID (e.g. '2020-08495')."""
    for f in VAULT_ARN.glob("*.md"):
        if arn_id in f.name:
            return f.read_text(encoding="utf-8")
    return ""
