#!/usr/bin/env python3
"""
Seed database from existing swiftclaim-obsidian vault.
Run once after installing backend dependencies.
"""
import re
import sys
from pathlib import Path
from typing import Tuple, Dict, Any

sys.path.insert(0, str(Path(__file__).parent))

from app.db import init_db, SessionLocal
from app.models import ARNDecision


VAULT_ARN = Path(__file__).parent.parent / "swiftclaim-obsidian" / "ARN"


def parse_frontmatter(text: str) -> Tuple[Dict[str, Any], str]:
    data: Dict[str, Any] = {}
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            fm_text = parts[1].strip()
            body = parts[2].strip()
            try:
                import yaml
                data = yaml.safe_load(fm_text) or {}
            except Exception:
                for line in fm_text.split("\n"):
                    line = line.strip()
                    if ":" in line:
                        k, _, v = line.partition(":")
                        data[k.strip()] = v.strip().strip('"').strip("'")
    return data, body


def seed():
    init_db()
    db = SessionLocal()

    if not VAULT_ARN.exists():
        print("ARN vault not found at", VAULT_ARN)
        db.close()
        return

    imported = 0
    updated = 0

    for md in sorted(VAULT_ARN.glob("*.md")):
        text = md.read_text(encoding="utf-8").strip()
        fm, body = parse_frontmatter(text)

        case_id = fm.get("case_id", "") or re.sub(r"^ARN\s+", "", md.stem)

        existing = db.query(ARNDecision).filter(ARNDecision.id == case_id).first()

        if existing:
            if body.strip():
                existing.body_markdown = body
                existing.category = fm.get("category", existing.category or "")
                existing.outcome = fm.get("outcome", existing.outcome or "")
                existing.legal_basis = fm.get("legal_basis", existing.legal_basis or [])
                existing.keywords = fm.get("keywords", existing.keywords or [])
                updated += 1
        else:
            db.add(ARNDecision(
                id=case_id,
                filename=md.name,
                category=fm.get("category", ""),
                subcategory=fm.get("subcategory", ""),
                date=fm.get("date", ""),
                outcome=fm.get("outcome", ""),
                insurer=fm.get("insurer", ""),
                damage_type=fm.get("damage_type", ""),
                claim_amount_sek=fm.get("claim_amount_sek"),
                legal_basis=fm.get("legal_basis") or [],
                keywords=fm.get("keywords") or [],
                body_markdown=body,
                raw_text="",
            ))
            imported += 1

    db.commit()
    db.close()
    print("Seeded", imported, "ARN decisions, updated", updated)


if __name__ == "__main__":
    seed()