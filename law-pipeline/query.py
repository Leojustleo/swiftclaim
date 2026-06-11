"""
query.py — Demo RAG over law-vault/. Voyage embeddings + Claude (via OpenRouter).

Usage:
    python query.py "din fråga på svenska"
    python query.py --reindex "din fråga"     # rebuild embedding cache

Embeddings cached in law-pipeline/.embeddings.json (gitignored).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Optional

import httpx
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

console = Console()

VAULT       = Path(__file__).parent.parent / "swiftclaim-obsidian"
CACHE_FILE  = Path(__file__).parent / ".embeddings.json"
VOYAGE_URL  = "https://api.voyageai.com/v1/embeddings"
OR_URL      = "https://openrouter.ai/api/v1/chat/completions"
EMBED_MODEL = "voyage-3"
CHAT_MODEL  = "moonshotai/kimi-k2.6"
TOP_K       = 8

SYSTEM_PROMPT = """Du är en svensk försäkringsjurist som hjälper Swiftclaim att bygga argument för högre utbetalningar i sakskadeärenden.

Du får ett utdrag från en juridisk kunskapsbas (ARN-beslut, lagrum, koncept) som är relevant för användarens fråga.

REGLER FÖR DITT SVAR:
1. Svara alltid på svenska.
2. Citera ALLTID källorna med Obsidian-stilen [[Titel]] när du refererar till lagrum eller ARN-beslut. Titeln är filnamnet utan .md-suffix.
3. Strukturera svaret som: (1) Sammanfattat svar, (2) Tillämpliga lagrum med citerade §§, (3) Relevanta ARN-fall och deras utfall, (4) Argumentationslinjer för Swiftclaim.
4. Om kunskapsbasen inte ger underlag för en del av frågan, säg det explicit. Hitta inte på.
5. Var konkret och praktisk — Swiftclaim ska kunna använda svaret direkt mot ett försäkringsbolag.
"""


# ─── Vault loading ────────────────────────────────────────────────────────────

def load_notes() -> list[dict]:
    """Load all markdown notes from the vault. Returns list of {path, title, text}."""
    notes = []
    for md in sorted(VAULT.rglob("*.md")):
        text = md.read_text(encoding="utf-8").strip()
        if not text or len(text) < 80:
            continue
        title = md.stem
        rel = md.relative_to(VAULT).as_posix()
        notes.append({"path": rel, "title": title, "text": text})
    return notes


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# ─── Voyage embeddings ────────────────────────────────────────────────────────

def voyage_embed(texts: list[str], api_key: str, input_type: str, batch_size: int = 8) -> list[list[float]]:
    """Batch embed with retry on 429 (free-tier rate limits: 3 RPM / 10K TPM)."""
    out: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i+batch_size]
        wait = 25  # initial backoff (free tier = 3 RPM → 20s between calls)
        for attempt in range(6):
            r = httpx.post(
                VOYAGE_URL,
                json={"input": batch, "model": EMBED_MODEL, "input_type": input_type},
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=60,
            )
            if r.status_code == 200:
                out.extend([d["embedding"] for d in r.json()["data"]])
                if i + batch_size < len(texts):
                    time.sleep(22)  # respect 3 RPM free tier
                break
            if r.status_code == 429:
                console.print(f"[yellow]Voyage rate-limited, waiting {wait}s (attempt {attempt+1}/6)[/yellow]")
                time.sleep(wait)
                wait = min(wait * 2, 120)
                continue
            raise RuntimeError(f"Voyage API error {r.status_code}: {r.text[:500]}")
        else:
            raise RuntimeError(f"Voyage rate-limit retries exhausted on batch starting at index {i}")
    return out


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x*y for x, y in zip(a, b))
    na  = math.sqrt(sum(x*x for x in a))
    nb  = math.sqrt(sum(y*y for y in b))
    return dot / (na * nb) if na and nb else 0.0


# ─── Index management ────────────────────────────────────────────────────────

def build_or_load_index(notes: list[dict], voyage_key: str, force: bool = False) -> dict:
    """Returns {path: {hash, embedding}} for all notes. Embeds only what's new/stale."""
    cache: dict = {}
    if CACHE_FILE.exists() and not force:
        cache = json.loads(CACHE_FILE.read_text())

    needs_embed = []
    for n in notes:
        h = content_hash(n["text"])
        entry = cache.get(n["path"])
        if not entry or entry.get("hash") != h:
            needs_embed.append((n, h))

    if needs_embed:
        console.print(f"[cyan]Embedding {len(needs_embed)} new/changed notes with Voyage...[/cyan]")
        # Embed in chunks, persisting cache between chunks so partial progress survives Ctrl-C / rate-limit failures.
        CHUNK = 8
        for start in range(0, len(needs_embed), CHUNK):
            chunk = needs_embed[start:start+CHUNK]
            embeddings = voyage_embed(
                [f"{n['title']}\n\n{n['text']}" for n, _ in chunk],
                voyage_key, input_type="document",
            )
            for (n, h), emb in zip(chunk, embeddings):
                cache[n["path"]] = {"hash": h, "embedding": emb}
            CACHE_FILE.write_text(json.dumps(cache))
            console.print(f"[dim]  saved {min(start+CHUNK, len(needs_embed))}/{len(needs_embed)}[/dim]")
        console.print(f"[green]Cached embeddings → {CACHE_FILE.name}[/green]")
    else:
        console.print(f"[dim]Index up to date ({len(cache)} notes cached)[/dim]")

    return cache


# ─── Retrieval ───────────────────────────────────────────────────────────────

def retrieve(query: str, index: dict, notes_by_path: dict, voyage_key: str, k: int = TOP_K) -> list[tuple[float, dict]]:
    q_emb = voyage_embed([query], voyage_key, input_type="query")[0]
    scored = []
    for path, entry in index.items():
        if path not in notes_by_path:
            continue
        score = cosine(q_emb, entry["embedding"])
        scored.append((score, notes_by_path[path]))
    scored.sort(key=lambda x: -x[0])
    return scored[:k]


# ─── Chat ────────────────────────────────────────────────────────────────────

def ask_claude(query: str, hits: list[tuple[float, dict]], or_key: str) -> str:
    context_parts = []
    for score, note in hits:
        context_parts.append(f"=== [[{note['title']}]] (score={score:.3f}, path={note['path']}) ===\n{note['text']}")
    context = "\n\n".join(context_parts)

    user_msg = f"""KUNSKAPSBAS (de {len(hits)} mest relevanta noteringarna från vault):

{context}

---

FRÅGA: {query}

Svara enligt reglerna i system-prompten. Använd [[Titel]] för alla källcitat."""

    r = httpx.post(
        OR_URL,
        json={
            "model": CHAT_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            "max_tokens": 2500,
        },
        headers={"Authorization": f"Bearer {or_key}"},
        timeout=120,
    )
    if r.status_code != 200:
        raise RuntimeError(f"OpenRouter API error {r.status_code}: {r.text[:500]}")
    return r.json()["choices"][0]["message"]["content"]


# ─── Main ────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Demo RAG over law-vault/")
    parser.add_argument("question", nargs="?", help="Question in Swedish")
    parser.add_argument("--reindex", action="store_true", help="Force re-embed all notes")
    parser.add_argument("-k", type=int, default=TOP_K, help=f"Top-K retrieval (default {TOP_K})")
    args = parser.parse_args()

    if not args.question:
        console.print("[red]Provide a question: python query.py \"...\"[/red]")
        return 1

    voyage_key = os.environ.get("VOYAGE_API_KEY")
    or_key     = os.environ.get("OPENROUTER_API_KEY")
    if not voyage_key or not or_key:
        console.print("[red]Set VOYAGE_API_KEY and OPENROUTER_API_KEY in .env[/red]")
        return 1

    notes = load_notes()
    if not notes:
        console.print(f"[red]No notes in {VAULT} — run main.py first[/red]")
        return 1
    console.print(f"[dim]Loaded {len(notes)} notes from vault[/dim]")
    notes_by_path = {n["path"]: n for n in notes}

    index = build_or_load_index(notes, voyage_key, force=args.reindex)

    console.print(f"\n[bold cyan]Q:[/bold cyan] {args.question}\n")
    console.print(f"[dim]Retrieving top-{args.k}...[/dim]")
    hits = retrieve(args.question, index, notes_by_path, voyage_key, k=args.k)

    console.print("[bold]Hits (by similarity):[/bold]")
    for score, note in hits:
        console.print(f"  [dim]{score:.3f}[/dim]  {note['path']}")

    console.print("\n[dim]Asking Claude via OpenRouter...[/dim]\n")
    answer = ask_claude(args.question, hits, or_key)

    console.print(Panel(Markdown(answer), title="Svar", border_style="green"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
