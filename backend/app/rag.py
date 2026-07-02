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


# Excludes only whole-statute dumps (54k-1.2M chars); the largest real
# document is an NJA judgment at ~43k. Paragraph/villkor/praxis notes stay in.
MAX_NOTE_CHARS = 50000

DIR_MAP = {
    "lagstiftning": "Lagstiftning/",
    "arn": "ARN/",
    "praxis": "Praxis/",
    "villkor": "Villkor/",
    "forarbeten": "Förarbeten/",
    "vagledning": "Vägledning/",
}

SOURCE_URL_RE = re.compile(r'^source_url:\s*"?([^"\n]+?)"?\s*$', re.MULTILINE)

_INDEX: Dict[str, Any] = {"notes": None, "embeddings": None, "cache_mtime": None}

# Hybrid retrieval: exact Swedish legal terms (e.g. "åldersavdrag") are strong
# signals that pure cosine similarity misses; matched terms add a bounded boost.
LEXICAL_MAX_BOOST = 0.15
_TERM_RE = re.compile(r"[a-zåäö]{4,}")
_STOPWORDS = {
    "när", "vad", "hur", "vilka", "vilken", "vilket", "varför",
    "inte", "från", "till", "över", "under", "utan", "med", "och", "eller", "men",
    "bolaget", "göra", "gör", "gjort", "finns", "vara", "varit", "blir", "blev",
    "denna", "detta", "dessa", "deras", "enligt", "samt", "även", "efter",
}


def query_terms(query: str) -> List[str]:
    seen = []
    for t in _TERM_RE.findall((query or "").lower()):
        if t not in _STOPWORDS and t not in seen:
            seen.append(t)
    return seen


def idf_weights(terms: List[str], texts_lower: List[str]) -> Dict[str, float]:
    """Weight per term by rarity in the pool: ubiquitous terms ~0, rare terms ~1."""
    n = len(texts_lower)
    if n < 2:
        return {t: 1.0 for t in terms}
    weights = {}
    for t in terms:
        df = sum(1 for x in texts_lower if t in x)
        weights[t] = max(0.0, math.log(n / (1 + df)) / math.log(n))
    return weights


def lexical_boost(terms: List[str], note_text_lower: str,
                  weights: Optional[Dict[str, float]] = None) -> float:
    if not terms:
        return 0.0
    if weights is None:
        weights = {t: 1.0 for t in terms}
    total = sum(weights.values())
    if total <= 0:
        return 0.0
    matched = sum(weights[t] for t in terms if t in note_text_lower)
    return LEXICAL_MAX_BOOST * matched / total


def note_source_url(text: str) -> Optional[str]:
    m = SOURCE_URL_RE.search(text[:600])
    return m.group(1).strip() if m else None


EXCLUDED_TOP_DIRS = {"Index"}


def dir_prefixes(notes: List[NoteDict], dirs: Optional[List[str]] = None) -> Tuple[str, ...]:
    """Alias (DIR_MAP key) or literal top-level vault dir → path prefix.
    No dirs given → every discovered top-level dir except EXCLUDED_TOP_DIRS,
    so new data sources become retrievable without code changes."""
    if dirs:
        return tuple(DIR_MAP.get(d, f"{d.rstrip('/')}/") for d in dirs)
    tops = {n["path"].split("/", 1)[0] for n in notes if "/" in n["path"]}
    return tuple(f"{t}/" for t in sorted(tops) if t not in EXCLUDED_TOP_DIRS)


def eligible_notes(notes: List[NoteDict], dirs: Optional[List[str]] = None) -> List[NoteDict]:
    prefixes = dir_prefixes(notes, dirs)
    if not prefixes:
        return []
    return [n for n in notes if n["path"].startswith(prefixes) and len(n["text"]) <= MAX_NOTE_CHARS]


def _cache_mtime() -> Optional[float]:
    return EMBED_CACHE.stat().st_mtime if EMBED_CACHE.exists() else None


def get_index() -> Tuple[List[NoteDict], Dict[str, Any]]:
    """Singleton vault index: notes + embeddings, reloaded only when the cache file changes."""
    if _INDEX["notes"] is None or _INDEX["cache_mtime"] != _cache_mtime():
        notes = load_vault_notes()
        embeddings = build_or_load_index(notes)
        _INDEX.update(notes=notes, embeddings=embeddings, cache_mtime=_cache_mtime())
    return _INDEX["notes"], _INDEX["embeddings"]


def reindex_vault(vault_path: Optional[Path] = None) -> Dict[str, Any]:
    """Incremental reindex: embed only new/changed vault files, then force
    the singleton index to reload. Safe to call any time new data lands."""
    notes = load_vault_notes(vault_path)
    cache: Dict[str, Any] = {}
    if EMBED_CACHE.exists():
        cache = json.loads(EMBED_CACHE.read_text())
    stale = [n for n in notes
             if (cache.get(n["path"]) or {}).get("hash") != _content_hash(n["text"])]
    build_or_load_index(notes)
    _INDEX["notes"] = None
    return {"total_notes": len(notes), "embedded": len(stale)}


def embed_queries(queries: List[str]) -> List[FloatList]:
    return voyage_embed(queries, _get_voyage_key(), input_type="query")


def _hit(score: float, n: NoteDict) -> NoteDict:
    return {
        "score": round(score, 4),
        "title": n["title"],
        "path": n["path"],
        "text": n["text"][:2000],
        "source_url": note_source_url(n["text"]),
    }


def search_with_embedding(q_emb: FloatList, dirs: Optional[List[str]] = None,
                          k: int = 5, min_score: float = 0.0,
                          query_text: str = "") -> List[NoteDict]:
    notes, index = get_index()
    pool = {n["path"]: n for n in eligible_notes(notes, dirs)}
    terms = query_terms(query_text)
    weights = None
    if terms:
        for n in pool.values():
            if "text_lower" not in n:
                n["text_lower"] = n["text"].lower()
        weights = idf_weights(terms, [n["text_lower"] for n in pool.values()])
    scored: List[ScoredNote] = []
    for path, entry in index.items():
        n = pool.get(path)
        if n is None:
            continue
        s = _cosine(q_emb, entry["embedding"])
        if terms:
            s += lexical_boost(terms, n["text_lower"], weights)
        if s >= min_score:
            scored.append((s, n))
    scored.sort(key=lambda x: -x[0])
    return [_hit(s, n) for s, n in scored[:k]]


def search_vault(query: str, dirs: Optional[List[str]] = None,
                 k: int = 5, min_score: float = 0.0) -> List[NoteDict]:
    return search_with_embedding(embed_queries([query])[0], dirs=dirs, k=k,
                                 min_score=min_score, query_text=query)


def search_law(query: str, k: int = 5) -> List[NoteDict]:
    return search_vault(query, dirs=None, k=k)


def search_precedents(damage_category: str, insurer_decision_text: str = "", k: int = 5) -> List[NoteDict]:
    query = f"skada {damage_category} f\u00f6rs\u00e4kring"
    if insurer_decision_text:
        query += f" {insurer_decision_text[:200]}"
    return search_vault(query, dirs=["arn"], k=k)