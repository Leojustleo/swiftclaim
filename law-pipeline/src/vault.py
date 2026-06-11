"""
vault.py — Writes processed decisions to an Obsidian vault.

Creates:
  - ARN/ARN {case_id}.md          — one file per decision
  - Lagstiftning/{statute}.md     — stub files for statutes (auto-created on first link)
  - Koncept/{concept}.md          — stub files for legal concepts
  - Index/Försäkring.md           — auto-generated category index
  - _attachments/                 — symlink or copy raw PDFs
"""

import re
import json
from pathlib import Path
from collections import defaultdict
from datetime import datetime

from rich.console import Console
from rich.table import Table

console = Console()


# ─── Statute stub template ────────────────────────────────────────────────────

STATUTE_STUB = """---
type: lagrum
statute: "{name}"
full_name: "{full_name}"
---

# {name}

> Stub — fyll i med lagtext från Riksdagen API

## Relevanta ARN-fall
*(genereras automatiskt via backlinks i Obsidian)*

## Länk till lagtext
- [Riksdagen](https://www.riksdagen.se/sv/dokument-och-lagar/)
"""

CONCEPT_STUB = """---
type: koncept
concept: "{name}"
---

# {name}

> Juridiskt begrepp inom svensk försäkringsrätt.

## Definition
*(fyll i)*

## Relevanta ARN-fall
*(genereras automatiskt via backlinks i Obsidian)*

## Tillämpliga lagrum
*(fyll i)*
"""

CATEGORY_INDEX = """---
type: index
category: "{category}"
generated: "{date}"
---

# {category} — ARN-beslut

{count} beslut indexerade.

## Utfall
- Konsumenten vann: {won}
- Konsumenten förlorade: {lost}
- Delvis bifall: {partial}

## Alla beslut

{decision_list}
"""


# ─── Helpers ──────────────────────────────────────────────────────────────────

def extract_wiki_links(markdown: str) -> list[str]:
    """Extract all [[wiki-link]] targets from a markdown string."""
    return re.findall(r'\[\[([^\]]+)\]\]', markdown)


def extract_frontmatter_value(markdown: str, key: str) -> str:
    """Pull a single value from YAML frontmatter."""
    match = re.search(rf'^{key}:\s*["\']?([^"\'\n]+)["\']?', markdown, re.MULTILINE)
    return match.group(1).strip() if match else ""


def safe_filename(name: str) -> str:
    """Make a string safe for use as a filename."""
    name = re.sub(r'[<>:"/\\|?*]', '-', name)
    return name.strip('. ')


# ─── Vault writer ─────────────────────────────────────────────────────────────

class ObsidianVault:
    def __init__(
        self,
        vault_root: Path,
        arn_dir: Path,
        law_dir: Path,
        concept_dir: Path,
        index_dir: Path,
    ):
        self.root         = vault_root
        self.arn_dir      = arn_dir
        self.law_dir      = law_dir
        self.concept_dir  = concept_dir
        self.index_dir    = index_dir

        for d in [arn_dir, law_dir, concept_dir, index_dir]:
            d.mkdir(parents=True, exist_ok=True)

        # Track which stubs we've created to avoid duplicates
        self._created_stubs: set[str] = set()
        # Track decisions for index generation
        self._decisions: list[dict] = []

    def write_decision(self, markdown: str, filename: str) -> Path:
        """Write a processed decision markdown file to the ARN folder."""
        path = self.arn_dir / filename
        path.write_text(markdown, encoding="utf-8")

        # Track for index
        self._decisions.append({
            "filename":  filename,
            "case_id":   extract_frontmatter_value(markdown, "case_id"),
            "category":  extract_frontmatter_value(markdown, "category"),
            "date":      extract_frontmatter_value(markdown, "date"),
            "outcome":   extract_frontmatter_value(markdown, "outcome"),
            "insurer":   extract_frontmatter_value(markdown, "insurer"),
            "damage":    extract_frontmatter_value(markdown, "damage_type"),
        })

        # Auto-create stubs for any wiki-linked statutes / concepts
        self._create_stubs_from_links(extract_wiki_links(markdown))
        return path

    def _create_stubs_from_links(self, links: list[str]) -> None:
        """For each [[link]], create a stub file if it doesn't exist yet."""
        for link in links:
            if link in self._created_stubs:
                continue

            # Statute pattern: FAL X kap Y §, Konsumentköplagen X §, etc.
            if re.search(r'\d+\s*(?:kap\.?\s*)?\d*\s*§', link) or \
               any(kw in link.lower() for kw in ['lagen', 'förordning', 'kap', '§']):
                self._write_law_stub(link)

            # ARN case reference — don't create stubs for these (they'll exist as own files)
            elif re.match(r'ARN\s+\d{4}-\d+', link):
                pass

            # Everything else is a concept
            else:
                self._write_concept_stub(link)

            self._created_stubs.add(link)

    def _write_law_stub(self, name: str) -> None:
        """Create a stub page for a statute section."""
        filename = safe_filename(name) + ".md"
        path = self.law_dir / filename

        if path.exists():
            return

        # Try to guess full name
        full_name_map = {
            "FAL":               "Försäkringsavtalslagen (SFS 2005:104)",
            "Avtalslagen":       "Avtalslagen (SFS 1915:218)",
            "Konsumentköplagen": "Konsumentköplagen (SFS 2022:260)",
            "Köplagen":          "Köplagen (SFS 1990:931)",
        }
        full_name = next(
            (v for k, v in full_name_map.items() if k.lower() in name.lower()),
            name
        )

        content = STATUTE_STUB.format(name=name, full_name=full_name)
        path.write_text(content, encoding="utf-8")

    def _write_concept_stub(self, name: str) -> None:
        """Create a stub page for a legal concept."""
        filename = safe_filename(name) + ".md"
        path = self.concept_dir / filename

        if path.exists():
            return

        content = CONCEPT_STUB.format(name=name)
        path.write_text(content, encoding="utf-8")

    def write_indexes(self) -> None:
        """Generate category index pages from tracked decisions."""
        by_category = defaultdict(list)
        for d in self._decisions:
            by_category[d["category"]].append(d)

        for category, decisions in by_category.items():
            won     = sum(1 for d in decisions if d["outcome"] == "consumer_won")
            lost    = sum(1 for d in decisions if d["outcome"] == "consumer_lost")
            partial = sum(1 for d in decisions if d["outcome"] == "partially_won")

            decision_lines = []
            for d in sorted(decisions, key=lambda x: x["date"], reverse=True):
                case_note = f"[[ARN/{d['filename'].replace('.md','')}|ARN {d['case_id']}]]"
                outcome_emoji = {
                    "consumer_won":   "✅",
                    "consumer_lost":  "❌",
                    "partially_won":  "⚖️",
                }.get(d["outcome"], "❓")
                decision_lines.append(
                    f"- {outcome_emoji} {case_note} — {d['date']} — {d['insurer'] or '?'} — {d['damage']}"
                )

            content = CATEGORY_INDEX.format(
                category=category,
                date=datetime.today().strftime("%Y-%m-%d"),
                count=len(decisions),
                won=won,
                lost=lost,
                partial=partial,
                decision_list="\n".join(decision_lines),
            )

            filename = safe_filename(category) + ".md"
            (self.index_dir / filename).write_text(content, encoding="utf-8")

        console.print(f"[green]✓ Created {len(by_category)} index pages[/green]")

    def write_summary_json(self, out_path: Path) -> None:
        """Save a JSON summary of all processed decisions for debugging."""
        out_path.write_text(
            json.dumps(self._decisions, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    def print_stats(self) -> None:
        """Print a summary table to the console."""
        table = Table(title="Vault Summary")
        table.add_column("Metric")
        table.add_column("Count", justify="right")

        by_outcome = defaultdict(int)
        for d in self._decisions:
            by_outcome[d["outcome"]] += 1

        table.add_row("Total decisions", str(len(self._decisions)))
        table.add_row("Consumer won",    str(by_outcome.get("consumer_won", 0)))
        table.add_row("Consumer lost",   str(by_outcome.get("consumer_lost", 0)))
        table.add_row("Partial",         str(by_outcome.get("partially_won", 0)))
        table.add_row("Law stubs",       str(len(list(self.law_dir.glob("*.md")))))
        table.add_row("Concept stubs",   str(len(list(self.concept_dir.glob("*.md")))))
        console.print(table)


# ─── Main write function ──────────────────────────────────────────────────────

def write_to_vault(
    processed_decisions: list,   # list of ProcessedDecision
    vault: ObsidianVault,
) -> None:
    """Write all processed decisions to the vault."""
    written = 0
    for decision in processed_decisions:
        if not decision.success:
            continue

        path = vault.write_decision(decision.markdown, decision.filename)
        console.print(f"  [green]→ {path.relative_to(vault.root)}[/green]")
        written += 1

    console.print(f"\n[bold green]Wrote {written} decision files to vault[/bold green]")

    vault.write_indexes()
    vault.print_stats()
