import hashlib
import json
import math
import os
import re
import time
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Any, Union

import httpx


VAULT_PATH = Path(__file__).parent.parent.parent / "swiftclaim-obsidian"
EMBED_CACHE = Path(__file__).parent.parent.parent / "law-pipeline" / ".embeddings.json"

VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"
EMBED_MODEL = "voyage-3"
DEFAULT_TOP_K = 8

NoteDict = Dict[str, Any]
FloatList = List[float]
ScoredNote = Tuple[float, NoteDict]


def _get_voyage_key() -> str:
    key = os.environ.get("VOYAGE_API_KEY")
    if not key:
        env_file = Path(__file__).parent.parent.parent / "law-pipeline" / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("VOYAGE_API_KEY="):
                    key = line.split("=", 1)[1].strip()
                    break
    if not key:
        raise RuntimeError("VOYAGE_API_KEY not set")
    return key


def voyage_embed(texts: List[str], api_key: str, input_type: str, batch_size: int = 8) -> List[FloatList]:
    out: List[FloatList] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        wait = 25
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
                    time.sleep(22)
                break
            if r.status_code == 429:
                time.sleep(wait)
                wait = min(wait * 2, 120)
                continue
            raise RuntimeError(f"Voyage API error {r.status_code}: {r.text[:500]}")
        else:
            raise RuntimeError(f"Voyage retries exhausted at index {i}")
    return out


def _cosine(a: FloatList, b: FloatList) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def load_vault_notes(vault_path: Optional[Path] = None, filter_paths: Optional[List[str]] = None) -> List[NoteDict]:
    vault_path = vault_path or VAULT_PATH
    notes: List[NoteDict] = []
    for md in sorted(vault_path.rglob("*.md")):
        if md.name.startswith("."):
            continue
        text = md.read_text(encoding="utf-8").strip()
        if not text or len(text) < 80:
            continue
        rel = md.relative_to(vault_path).as_posix()
        if filter_paths and rel not in filter_paths:
            continue
        if rel.startswith("Koncept/") and "fyll i" in text[:200].lower():
            continue
        notes.append({"path": rel, "title": md.stem, "text": text})
    return notes


def build_or_load_index(notes: List[NoteDict], force: bool = False) -> Dict[str, Any]:
    voyage_key = _get_voyage_key()
    cache: Dict[str, Any] = {}
    if EMBED_CACHE.exists() and not force:
        cache = json.loads(EMBED_CACHE.read_text())

    needs_embed: List[Tuple[NoteDict, str]] = []
    for n in notes:
        h = _content_hash(n["text"])
        entry = cache.get(n["path"])
        if not entry or entry.get("hash") != h:
            needs_embed.append((n, h))

    if needs_embed:
        chunk = 8
        for start in range(0, len(needs_embed), chunk):
            batch = needs_embed[start : start + chunk]
            embeddings = voyage_embed(
                [f"{n['title']}\n\n{n['text']}" for n, _ in batch], voyage_key, input_type="document"
            )
            for (n, h), emb in zip(batch, embeddings):
                cache[n["path"]] = {"hash": h, "embedding": emb}
            EMBED_CACHE.write_text(json.dumps(cache))

    return cache


def retrieve(query: str, k: int = DEFAULT_TOP_K, notes: Optional[List[NoteDict]] = None) -> List[ScoredNote]:
    voyage_key = _get_voyage_key()

    if notes is None:
        notes = load_vault_notes()

    notes_by_path = {n["path"]: n for n in notes}
    index = build_or_load_index(notes)

    q_emb = voyage_embed([query], voyage_key, input_type="query")[0]
    scored: List[ScoredNote] = []
    for path, entry in index.items():
        if path not in notes_by_path:
            continue
        score = _cosine(q_emb, entry["embedding"])
        scored.append((score, notes_by_path[path]))
    scored.sort(key=lambda x: -x[0])
    return scored[:k]


def search_law(query: str, k: int = 5) -> List[NoteDict]:
    notes = load_vault_notes(filter_paths=None)
    law_notes = [n for n in notes if n["path"].startswith("Lagstiftning/") or n["path"].startswith("ARN/")]
    hits = retrieve(query, k=k, notes=law_notes)
    return [{"score": round(s, 4), "title": n["title"], "path": n["path"], "text": n["text"][:2000]} for s, n in hits]


def search_precedents(damage_category: str, insurer_decision_text: str = "", k: int = 5) -> List[NoteDict]:
    query = "skada " + damage_category + " f" + "\u00f6" + "rs" + "\u00e4" + "kring"
    if insurer_decision_text:
        query += f" {insurer_decision_text[:200]}"
    arn_notes = [n for n in load_vault_notes() if n["path"].startswith("ARN/")]
    if not arn_notes:
        return []
    hits = retrieve(query, k=k, notes=arn_notes)
    return [{"score": round(s, 4), "title": n["title"], "path": n["path"], "text": n["text"][:2000]} for s, n in hits]