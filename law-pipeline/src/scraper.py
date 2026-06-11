"""
scraper.py — Downloads ARN decision PDFs from arn.se

Fetches the vägledande beslut index page, extracts all PDF links,
filters by category, then downloads each PDF with polite rate limiting.
"""

import asyncio
import html
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

import httpx
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

console = Console()


@dataclass
class DecisionMeta:
    """Metadata extracted from the ARN index page for one decision."""
    case_id:    str
    category:   str
    date:       str
    summary:    str
    pdf_url:    str
    year:       str = field(init=False)

    def __post_init__(self):
        self.year = self.date[:4] if self.date else "unknown"

    @property
    def safe_id(self) -> str:
        return self.case_id.replace("/", "_").replace(" ", "_")

    @property
    def pdf_filename(self) -> str:
        return f"{self.safe_id}.pdf"


def parse_decisions_from_html(page_html: str, base_url: str = "https://www.arn.se") -> list[DecisionMeta]:
    """
    Parse the vägledande beslut page HTML.
    Each decision block in the source HTML looks like:

        <h3>Försäkring, Beslut 2022-10-24</h3>
        <p>Some summary text...</p>
        <p><a href="/globalassets/.../arendereferat-2021-17230.pdf">Referat 2021-17230</a></p>
    """
    decisions = []

    pattern = re.compile(
        r'<h3>\s*([^,<]+?),\s*[Bb]eslut\s+(\d{4}-\d{2}-\d{2})\s*</h3>'  # heading
        r'(.*?)'                                                          # summary block
        r'<a[^>]+href="([^"]+arendereferat-[\d-]+\.pdf)"',                # pdf link
        re.DOTALL | re.IGNORECASE,
    )

    case_id_re = re.compile(r'arendereferat-+(\d{4}-\d+)\.pdf', re.IGNORECASE)
    tag_re     = re.compile(r'<[^>]+>')

    for m in pattern.finditer(page_html):
        category   = html.unescape(m.group(1)).strip()
        date       = m.group(2).strip()
        body       = m.group(3)
        pdf_path   = m.group(4)

        cid_match = case_id_re.search(pdf_path)
        if not cid_match:
            continue
        case_id = cid_match.group(1)

        # Absolute URL
        pdf_url = pdf_path if pdf_path.startswith("http") else base_url.rstrip("/") + pdf_path

        # Strip tags + entities from summary
        summary = tag_re.sub(" ", body)
        summary = html.unescape(summary)
        summary = re.sub(r"\s+", " ", summary).strip()

        decisions.append(DecisionMeta(
            case_id=case_id,
            category=category,
            date=date,
            summary=summary,
            pdf_url=pdf_url,
        ))

    return decisions


def filter_by_category(
    decisions: list[DecisionMeta],
    category_filter: Optional[list[str]]
) -> list[DecisionMeta]:
    """Keep only decisions matching the category filter (case-insensitive)."""
    if not category_filter:
        return decisions

    normalized = [c.lower() for c in category_filter]

    def matches(d: DecisionMeta) -> bool:
        cat = d.category.lower()
        return any(f in cat for f in normalized)

    return [d for d in decisions if matches(d)]


async def fetch_html(client: httpx.AsyncClient, url: str, rate: float) -> str:
    await asyncio.sleep(rate)
    resp = await client.get(url)
    resp.raise_for_status()
    return resp.text


async def download_pdf(
    client: httpx.AsyncClient,
    decision: DecisionMeta,
    out_dir: Path,
    rate: float,
    semaphore: asyncio.Semaphore,
) -> tuple[DecisionMeta, bool]:
    """Download one PDF. Returns (decision, success)."""
    out_path = out_dir / decision.pdf_filename

    if out_path.exists():
        return decision, True   # already downloaded

    async with semaphore:
        await asyncio.sleep(rate)
        try:
            resp = await client.get(decision.pdf_url)
            resp.raise_for_status()
            out_path.write_bytes(resp.content)
            return decision, True
        except Exception as e:
            console.print(f"[red]✗ {decision.case_id}: {e}[/red]")
            return decision, False


async def scrape(
    base_url: str,
    decisions_page: str,
    out_dir: Path,
    category_filter: Optional[list[str]],
    rate_limit: float,
    max_concurrent: int,
    user_agent: str,
) -> list[tuple[DecisionMeta, Path]]:
    """
    Full scrape run.
    Returns list of (DecisionMeta, pdf_path) for all successfully downloaded PDFs.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": user_agent}

    async with httpx.AsyncClient(
        base_url=base_url,
        headers=headers,
        timeout=60,
        follow_redirects=True,
    ) as client:

        # 1. Fetch index
        console.print(f"[cyan]Fetching ARN index from {base_url + decisions_page}[/cyan]")
        html = await fetch_html(client, decisions_page, rate=0)

        # 2. Parse all decisions
        all_decisions = parse_decisions_from_html(html)
        console.print(f"[green]Found {len(all_decisions)} total decisions[/green]")

        # 3. Filter
        decisions = filter_by_category(all_decisions, category_filter)
        console.print(f"[green]After category filter: {len(decisions)} decisions[/green]")

        if not decisions:
            console.print("[yellow]No decisions matched filter. Check CATEGORY_FILTER in config.py[/yellow]")
            return []

        # 4. Download PDFs with concurrency limit
        semaphore = asyncio.Semaphore(max_concurrent)
        tasks = [
            download_pdf(client, d, out_dir, rate_limit, semaphore)
            for d in decisions
        ]

        results = []
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
        ) as progress:
            task = progress.add_task("Downloading PDFs...", total=len(tasks))

            for coro in asyncio.as_completed(tasks):
                decision, success = await coro
                progress.advance(task)
                if success:
                    pdf_path = out_dir / decision.pdf_filename
                    results.append((decision, pdf_path))

    console.print(f"[bold green]✓ Downloaded {len(results)}/{len(decisions)} PDFs[/bold green]")
    return results
