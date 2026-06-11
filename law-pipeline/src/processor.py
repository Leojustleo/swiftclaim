"""
processor.py — LLM layer that converts raw ARN decision text into
structured Obsidian markdown with YAML frontmatter and wiki-links.

Uses Claude (via OpenRouter, OpenAI-compatible API) to:
  1. Anonymize all personal data (names, addresses, personnummer)
  2. Extract structured metadata (outcome, legal basis, damage type, etc.)
  3. Add [[wiki-links]] to statutes, concepts, and related cases
  4. Write clean, consistently formatted markdown
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass

from openai import OpenAI, RateLimitError, APIError
from rich.console import Console

LLM_BASE_URL = "https://api.deepseek.com/v1"

console = Console()

# ─── Prompt ───────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Du är ett juridiskt databehandlingssystem som omvandlar svenska ARN-beslut till strukturerade Obsidian-anteckningar.

REGLER FÖR ANONYMISERING (OBLIGATORISKT — GDPR):
- Ta bort ALLA personnamn (konsument, företrädare, vittnen) — ersätt med "konsumenten" eller "bolaget"
- Ta bort ALLA personnummer, adresser, postnummer, specifika ortsangivelser
- Generalisera unika detaljer: "57-årig lärare i Luleå" → "en konsument"
- Avrunda ovanliga belopp: exakta udda belopp → närmaste 10 000 kr-intervall
- Behåll: försäkringsbolagets namn (det är juridiskt relevant), ärendenummer, datum, lagrum

OUTPUT: Endast ren markdown. Inga förklaringar, inga kodblock, ingen preamble.

FORMAT:

---
case_id: "{case_id}"
category: {category}
subcategory: {subcategory}
date: {YYYY-MM-DD}
outcome: {consumer_won | consumer_lost | partially_won | not_tried}
insurer: "{bolagsnamn eller okänt}"
damage_type: {water | fire | theft | liability | property | travel | other}
claim_amount_sek: {belopp i SEK som heltal, eller null}
legal_basis:
  - "{lagrum 1}"
  - "{lagrum 2}"
keywords:
  - "{nyckelord 1}"
  - "{nyckelord 2}"
---

# ARN {case_id} — {kort beskrivande rubrik}

## Bakgrund
{2-4 meningar om bakgrunden, anonymiserad}

## Parternas ståndpunkter
**Konsumenten:** {vad konsumenten yrkade och argumenterade}

**Bolaget:** {vad bolaget invände}

## ARN:s bedömning
{Nämndens juridiska resonemang — behåll lagrumshänvisningar som [[wiki-links]]}

## Utfall
**{Konsumenten vann / Konsumenten förlorade / Delvis bifall}** — {en mening om vad som rekommenderades}

## Tillämpliga lagrum
{Lista lagrum som [[FAL 4 kap 6 §]], [[Avtalslagen 36 §]] etc.}

## Juridiska koncept
{Lista relevanta koncept som [[Säkerhetsföreskrift]], [[Nedsättningsrätt]] etc.}

## Relaterade fall
{Om du känner igen liknande ARN-fall från texten, länka dem som [[ARN XXXX-XXXXX]]}

---
*Källa: Allmänna reklamationsnämnden — offentlig handling*

WIKI-LINK REGLER:
- Lagrum: [[FAL 4 kap 6 §]], [[Konsumentköplagen 4 §]], [[Avtalslagen 36 §]]
- Försäkringsavtalslagen förkortas alltid FAL
- Juridiska koncept: [[Säkerhetsföreskrift]], [[Nedsättningsrätt]], [[Omfattningsvillkor]], [[Karens]], [[Självriskreduktion]]
- Subcategory för försäkring: hemförsäkring | villaförsäkring | båtförsäkring | reseförsäkring | bilförsäkring | övrig_försäkring
- Damage type för fastighet: water | fire | theft | vandalism | liability | other
"""

# ─── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class ProcessedDecision:
    case_id:    str
    markdown:   str
    success:    bool
    error:      str = ""

    @property
    def filename(self) -> str:
        safe = self.case_id.replace("/", "_").replace(" ", "_")
        return f"ARN {safe}.md"


# ─── LLM call ─────────────────────────────────────────────────────────────────

def process_decision(
    case_id: str,
    raw_text: str,
    category: str,
    summary: str,
    api_key: str,
    model: str,
    retry_count: int = 3,
) -> ProcessedDecision:
    """
    Send one decision to Claude and get back structured Obsidian markdown.
    Retries up to retry_count times on API errors.
    """
    client = OpenAI(api_key=api_key, base_url=LLM_BASE_URL)

    user_content = f"""Ärendenummer: {case_id}
Kategori: {category}
Sammanfattning från ARN: {summary}

--- BESLUTETS FULLTEXT ---
{raw_text}
"""

    for attempt in range(retry_count):
        try:
            response = client.chat.completions.create(
                model=model,
                max_tokens=8000,  # Kimi K2.6 is a reasoning model — needs headroom for thinking + output
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
            )
            markdown = (response.choices[0].message.content or "").strip()

            # Strip code fences (Kimi often wraps responses in ```...```)
            if markdown.startswith("```"):
                # Drop opening fence (with optional language tag) and trailing fence
                markdown = re.sub(r"^```[a-zA-Z]*\n?", "", markdown)
                markdown = re.sub(r"\n?```\s*$", "", markdown).strip()

            # Sanity check — should start with YAML frontmatter
            if not markdown.startswith("---"):
                markdown = "---\ncase_id: \"" + case_id + "\"\n---\n\n" + markdown

            return ProcessedDecision(
                case_id=case_id,
                markdown=markdown,
                success=True,
            )

        except RateLimitError:
            wait = 30 * (attempt + 1)
            console.print(f"[yellow]Rate limit hit, waiting {wait}s...[/yellow]")
            time.sleep(wait)

        except APIError as e:
            if attempt < retry_count - 1:
                time.sleep(5)
            else:
                return ProcessedDecision(
                    case_id=case_id,
                    markdown="",
                    success=False,
                    error=str(e),
                )

    return ProcessedDecision(
        case_id=case_id,
        markdown="",
        success=False,
        error="Max retries exceeded",
    )


# ─── Batch processing ─────────────────────────────────────────────────────────

def process_batch(
    items: list[tuple],   # (ExtractedDecision, DecisionMeta)
    api_key: str,
    model: str,
    delay_between: float = 0.5,
    limit: int | None = None,
) -> list[ProcessedDecision]:
    """Process a list of extracted decisions through the LLM."""
    if limit:
        items = items[:limit]

    results = []
    total = len(items)

    for i, (extracted, meta) in enumerate(items, 1):
        console.print(f"[cyan][{i}/{total}] Processing {meta.case_id} ({meta.category})...[/cyan]")

        if not extracted.is_usable:
            console.print(f"[yellow]  Skipped — unusable extraction[/yellow]")
            continue

        result = process_decision(
            case_id=meta.case_id,
            raw_text=extracted.raw_text,
            category=meta.category,
            summary=meta.summary,
            api_key=api_key,
            model=model,
        )

        if result.success:
            console.print(f"[green]  ✓ Done ({len(result.markdown):,} chars)[/green]")
        else:
            console.print(f"[red]  ✗ Failed: {result.error}[/red]")

        results.append(result)
        time.sleep(delay_between)

    won  = sum(1 for r in results if r.success)
    console.print(f"\n[bold green]LLM processing: {won}/{len(results)} succeeded[/bold green]")
    return results
