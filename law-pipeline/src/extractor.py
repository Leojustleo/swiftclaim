"""
extractor.py — Extracts clean text from ARN decision PDFs using pdfplumber.

ARN PDFs are typically 1-3 pages of structured Swedish legal text.
pdfplumber handles their formatting well without needing OCR.
"""
from __future__ import annotations

import re
from pathlib import Path
from dataclasses import dataclass

import pdfplumber
from rich.console import Console

console = Console()


@dataclass
class ExtractedDecision:
    """Raw text extracted from a PDF, with light cleaning applied."""
    case_id:    str
    pdf_path:   Path
    raw_text:   str
    page_count: int
    char_count: int
    success:    bool
    error:      str = ""

    @property
    def is_usable(self) -> bool:
        return self.success and self.char_count >= 200


def extract_text_from_pdf(pdf_path: Path) -> str:
    """
    Extract and lightly clean text from a PDF.

    pdfplumber preserves layout well for ARN PDFs. We join pages
    with a clear separator so the LLM can see page boundaries if needed.
    """
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text(x_tolerance=2, y_tolerance=3)
            if text:
                pages.append(text.strip())

    full_text = "\n\n---\n\n".join(pages)

    # Light cleaning
    full_text = re.sub(r'\n{3,}', '\n\n', full_text)   # collapse excess newlines
    full_text = re.sub(r' {2,}', ' ', full_text)        # collapse excess spaces
    full_text = full_text.strip()

    return full_text


def extract_decision(case_id: str, pdf_path: Path) -> ExtractedDecision:
    """Extract text from one PDF. Never raises — errors are captured in result."""
    try:
        text = extract_text_from_pdf(pdf_path)
        with pdfplumber.open(pdf_path) as pdf:
            page_count = len(pdf.pages)

        return ExtractedDecision(
            case_id=case_id,
            pdf_path=pdf_path,
            raw_text=text,
            page_count=page_count,
            char_count=len(text),
            success=True,
        )
    except Exception as e:
        console.print(f"[red]PDF extraction failed for {case_id}: {e}[/red]")
        return ExtractedDecision(
            case_id=case_id,
            pdf_path=pdf_path,
            raw_text="",
            page_count=0,
            char_count=0,
            success=False,
            error=str(e),
        )


def extract_batch(
    decisions: list[tuple],   # list of (DecisionMeta, Path)
    save_dir: Path | None = None,
) -> list[ExtractedDecision]:
    """
    Extract text from a list of (DecisionMeta, pdf_path) tuples.
    Optionally saves raw text to save_dir as .txt for debugging.
    """
    if save_dir:
        save_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for meta, pdf_path in decisions:
        extracted = extract_decision(meta.case_id, pdf_path)

        if save_dir and extracted.success:
            txt_path = save_dir / f"{meta.safe_id}.txt"
            txt_path.write_text(extracted.raw_text, encoding="utf-8")

        status = "✓" if extracted.is_usable else "⚠"
        chars  = f"{extracted.char_count:,} chars" if extracted.success else extracted.error
        console.print(f"  {status} [{meta.case_id}] {chars}")

        results.append(extracted)

    usable = sum(1 for r in results if r.is_usable)
    console.print(f"[green]Extracted {usable}/{len(results)} usable PDFs[/green]")
    return results
