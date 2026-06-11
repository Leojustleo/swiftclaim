"""
main.py — Orchestrates the full ARN → Obsidian pipeline.

Usage:
    python main.py                     # full run (scrape + process + write)
    python main.py --skip-scrape       # reuse already-downloaded PDFs
    python main.py --limit 10          # process only first 10 decisions (good for testing)
    python main.py --category forsakring  # override category filter
"""

import asyncio
import sys
import os
import argparse
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).parent))

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule

console = Console()


def parse_args():
    parser = argparse.ArgumentParser(
        description="ARN → Obsidian pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--skip-scrape",
        action="store_true",
        help="Skip downloading PDFs, use existing files in raw_pdfs/",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of decisions to process (useful for testing)",
    )
    parser.add_argument(
        "--category",
        type=str,
        default=None,
        help="Override CATEGORY_FILTER with a single category string",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="Anthropic API key (overrides config.py and ANTHROPIC_API_KEY env var)",
    )
    return parser.parse_args()


async def main():
    args = parse_args()

    # ── Load .env if present ───────────────────────────────────────────────
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent / ".env")
    except ImportError:
        pass

    # ── Import config ──────────────────────────────────────────────────────
    from config import (
        OPENROUTER_API_KEY, CLAUDE_MODEL,
        RAW_PDF_DIR, PROCESSED_DIR, OBSIDIAN_VAULT,
        VAULT_ARN, VAULT_LAW, VAULT_CONCEPTS, VAULT_INDEX,
        ARN_BASE_URL, ARN_DECISIONS_PAGE,
        CATEGORY_FILTER, RATE_LIMIT_SECONDS, MAX_CONCURRENT, USER_AGENT,
        MIN_TEXT_LENGTH, PROCESS_LIMIT,
    )

    # ── Resolve API key ────────────────────────────────────────────────────
    api_key = (
        args.api_key
        or os.environ.get("OPENROUTER_API_KEY")
        or OPENROUTER_API_KEY
    )
    if api_key == "YOUR_API_KEY_HERE":
        console.print("[bold red]Error: Set your OpenRouter API key in .env (OPENROUTER_API_KEY=...) or config.py[/bold red]")
        sys.exit(1)

    # ── Category filter ────────────────────────────────────────────────────
    category_filter = [args.category] if args.category else CATEGORY_FILTER
    limit = args.limit or PROCESS_LIMIT

    # ── Banner ─────────────────────────────────────────────────────────────
    console.print(Panel.fit(
        "[bold cyan]ARN → Obsidian Pipeline[/bold cyan]\n"
        f"Categories: {category_filter}\n"
        f"Limit: {limit or 'all'}\n"
        f"Model: {CLAUDE_MODEL}",
        border_style="cyan",
    ))

    # ══════════════════════════════════════════════════════════════════════
    # STEP 1: SCRAPE
    # ══════════════════════════════════════════════════════════════════════
    console.print(Rule("[bold]Step 1: Scrape ARN[/bold]"))

    from src.scraper import scrape

    if args.skip_scrape:
        console.print("[yellow]Skipping scrape — loading existing PDFs from raw_pdfs/[/yellow]")
        # Reconstruct a minimal list from existing PDF files
        # We need (DecisionMeta, Path) pairs — use filename to reconstruct case_id
        from src.scraper import DecisionMeta
        downloaded = []
        for pdf_path in sorted(RAW_PDF_DIR.glob("*.pdf")):
            case_id = pdf_path.stem.replace("arendereferat-", "").replace("_", "-")
            # Minimal meta — category unknown from filename alone
            meta = DecisionMeta(
                case_id=case_id,
                category="Försäkring",  # assume for now
                date="",
                summary="",
                pdf_url="",
            )
            downloaded.append((meta, pdf_path))
        console.print(f"Found {len(downloaded)} existing PDFs")
    else:
        downloaded = await scrape(
            base_url=ARN_BASE_URL,
            decisions_page=ARN_DECISIONS_PAGE,
            out_dir=RAW_PDF_DIR,
            category_filter=category_filter,
            rate_limit=RATE_LIMIT_SECONDS,
            max_concurrent=MAX_CONCURRENT,
            user_agent=USER_AGENT,
        )

    if not downloaded:
        console.print("[red]No PDFs to process. Exiting.[/red]")
        return

    # ══════════════════════════════════════════════════════════════════════
    # STEP 2: EXTRACT TEXT FROM PDFs
    # ══════════════════════════════════════════════════════════════════════
    console.print(Rule("[bold]Step 2: Extract PDF Text[/bold]"))

    from src.extractor import extract_batch

    extracted = extract_batch(
        decisions=downloaded,
        save_dir=PROCESSED_DIR,
    )

    # Pair extracted results back with their metadata
    paired = []
    for (meta, _), ext in zip(downloaded, extracted):
        if ext.is_usable:
            paired.append((ext, meta))

    console.print(f"Usable extractions: {len(paired)}/{len(downloaded)}")

    if not paired:
        console.print("[red]No usable text extracted. Check PDFs in raw_pdfs/[/red]")
        return

    # ══════════════════════════════════════════════════════════════════════
    # STEP 3: LLM PROCESSING
    # ══════════════════════════════════════════════════════════════════════
    console.print(Rule("[bold]Step 3: LLM Processing (Claude)[/bold]"))

    from src.processor import process_batch

    processed = process_batch(
        items=paired,
        api_key=api_key,
        model=CLAUDE_MODEL,
        limit=limit,
    )

    # ══════════════════════════════════════════════════════════════════════
    # STEP 4: WRITE TO OBSIDIAN VAULT
    # ══════════════════════════════════════════════════════════════════════
    console.print(Rule("[bold]Step 4: Write Obsidian Vault[/bold]"))

    from src.vault import ObsidianVault, write_to_vault

    vault = ObsidianVault(
        vault_root=OBSIDIAN_VAULT,
        arn_dir=VAULT_ARN,
        law_dir=VAULT_LAW,
        concept_dir=VAULT_CONCEPTS,
        index_dir=VAULT_INDEX,
    )

    write_to_vault(processed, vault)
    vault.write_summary_json(OBSIDIAN_VAULT / "summary.json")

    # ══════════════════════════════════════════════════════════════════════
    # DONE
    # ══════════════════════════════════════════════════════════════════════
    console.print(Rule())
    console.print(Panel.fit(
        f"[bold green]✓ Pipeline complete[/bold green]\n\n"
        f"Vault location: [cyan]{OBSIDIAN_VAULT.resolve()}[/cyan]\n\n"
        f"Open Obsidian → Open folder as vault → select the folder above",
        border_style="green",
    ))


if __name__ == "__main__":
    asyncio.run(main())
