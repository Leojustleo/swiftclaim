# Draft Generation v2 + Vault Q&A — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the blocking single-shot draft endpoint with an async, observable 4-stage pipeline (plan → retrieve → draft → verify) grounded in all 6 vault dataset types, plus a synchronous Q&A endpoint with verified references.

**Architecture:** New `llm.py` (provider chain + logging + PII scrub), `verify.py` (citation resolution), upgraded `rag.py` (in-memory singleton index, dir/threshold filtering), `draft_ai.py` (job pipeline via FastAPI BackgroundTasks + SQLite job rows), `qa_ai.py` (ask). OS dashboard polls jobs and renders verified/flagged citations.

**Tech Stack:** FastAPI, SQLAlchemy/SQLite (WAL), httpx, pydantic v2, Voyage embeddings, DeepSeek → OpenRouter chain, vanilla JS frontend, pytest.

**Spec:** `docs/superpowers/specs/2026-06-12-draft-generation-v2-design.md`

Run all backend commands from `backend/` with the repo venv python. Tests: `cd backend && python -m pytest tests/ -v`.

---

### Task 1: DB foundation — new tables, columns, WAL, schemas

**Files:**
- Modify: `backend/app/models.py`, `backend/app/db.py`, `backend/app/schemas.py`, `backend/requirements.txt`
- Test: `backend/tests/test_db.py` (+ empty `backend/tests/__init__.py`)

- [ ] **Step 1: Add pytest to requirements**

In `backend/requirements.txt` append:
```
pytest==8.3.4
```
Run: `pip install pytest==8.3.4`

- [ ] **Step 2: Write failing test**

`backend/tests/test_db.py`:
```python
from sqlalchemy import inspect

from app.db import engine, init_db


def test_new_tables_and_columns_exist():
    init_db()
    insp = inspect(engine)
    assert "draft_jobs" in insp.get_table_names()
    assert "llm_calls" in insp.get_table_names()
    draft_cols = {c["name"] for c in insp.get_columns("response_drafts")}
    assert {"flagged_citations", "evidence", "model_used", "job_id"} <= draft_cols
```

Run: `python -m pytest tests/test_db.py -v` → FAIL (no draft_jobs table).

- [ ] **Step 3: Add models**

In `backend/app/models.py` append:
```python
class DraftJob(Base):
    __tablename__ = "draft_jobs"

    id = Column(String, primary_key=True)
    case_id = Column(String, ForeignKey("cases.id"), index=True)
    status = Column(String, default="queued")  # queued, planning, retrieving, drafting, verifying, done, failed
    stages = Column(JSON, default={})
    error = Column(Text, nullable=True)
    draft_id = Column(Integer, nullable=True)
    pipeline_version = Column(String, default="2.0")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class LLMCall(Base):
    __tablename__ = "llm_calls"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String, nullable=True, index=True)
    stage = Column(String)
    provider = Column(String)
    model = Column(String)
    status = Column(String)  # ok, error
    error = Column(Text, nullable=True)
    latency_ms = Column(Integer, default=0)
    prompt_text = Column(Text)
    response_text = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
```

In `ResponseDraft` add after `status`:
```python
    flagged_citations = Column(JSON, default=[])
    evidence = Column(JSON, default=[])
    model_used = Column(String, nullable=True)
    job_id = Column(String, nullable=True)
```

- [ ] **Step 4: db.py — WAL, busy_timeout, migration**

Replace `engine = ...` line with:
```python
from sqlalchemy import create_engine, event

engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False, "timeout": 30})


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_connection, connection_record):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=30000")
    cur.close()
```

In `init_db()` change the import line to include new models:
```python
    from app.models import Case, ARNDecision, LawSection, ResponseDraft, KnowledgeNote, DraftJob, LLMCall
```

In `_migrate(engine)` append inside the `with` block:
```python
        draft_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(response_drafts)"))]
        for col, ddl in [
            ("flagged_citations", "ALTER TABLE response_drafts ADD COLUMN flagged_citations JSON"),
            ("evidence", "ALTER TABLE response_drafts ADD COLUMN evidence JSON"),
            ("model_used", "ALTER TABLE response_drafts ADD COLUMN model_used VARCHAR"),
            ("job_id", "ALTER TABLE response_drafts ADD COLUMN job_id VARCHAR"),
        ]:
            if col not in draft_cols:
                conn.execute(text(ddl))
        conn.commit()
```

- [ ] **Step 5: Schemas**

In `backend/app/schemas.py`: extend `ResponseDraftOut` with:
```python
    flagged_citations: List = []
    evidence: List = []
    model_used: Optional[str] = None
    job_id: Optional[str] = None
```

Append:
```python
class DraftJobOut(BaseModel):
    id: str
    case_id: str
    status: str
    error: Optional[str] = None
    stages: dict = {}
    draft: Optional[ResponseDraftOut] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AskRequest(BaseModel):
    question: str
    case_id: Optional[str] = None


class AskSource(BaseModel):
    ref: str
    title: str = ""
    path: str = ""
    score: float = 0.0
    source_url: Optional[str] = None


class AskOut(BaseModel):
    answer_markdown: str
    sources: List[AskSource] = []
    unverified_refs: List[str] = []
    model_used: Optional[str] = None
```

- [ ] **Step 6: Run test** → PASS. Also `python -c "from app.main import app"` still imports.

- [ ] **Step 7: Commit** `feat(backend): draft job + llm call tables, WAL, draft columns`

---

### Task 2: `llm.py` — PII scrub + provider chain + logging

**Files:**
- Create: `backend/app/llm.py`
- Test: `backend/tests/test_pii.py`, `backend/tests/test_llm_chain.py`

- [ ] **Step 1: Failing PII tests**

`backend/tests/test_pii.py`:
```python
from app.llm import scrub_pii, unscrub_pii

FIELDS = {
    "customer_name": "Anna Andersson",
    "customer_email": "anna@example.se",
    "customer_phone": "0701234567",
    "property_address": "Storgatan 1, Lund",
}


def test_scrub_replaces_all_pii():
    text = "Anna Andersson (anna@example.se, 0701234567) bor på Storgatan 1, Lund."
    out = scrub_pii(text, FIELDS)
    assert "Anna" not in out and "anna@" not in out and "070" not in out and "Storgatan" not in out
    assert "[KUND]" in out and "[EPOST]" in out and "[TELEFON]" in out and "[ADRESS]" in out


def test_round_trip():
    text = "Kund Anna Andersson kräver ersättning."
    assert unscrub_pii(scrub_pii(text, FIELDS), FIELDS) == text


def test_short_values_not_replaced():
    fields = {"customer_name": "AB", "customer_email": "", "customer_phone": "", "property_address": ""}
    assert scrub_pii("AB är ett vanligt ord", fields) == "AB är ett vanligt ord"
```

Run → FAIL (module missing).

- [ ] **Step 2: Create `backend/app/llm.py`**

```python
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Type

import httpx
from pydantic import BaseModel, ValidationError

PIPELINE_VERSION = "2.0"

BACKEND_ENV = Path(__file__).parent.parent / ".env"
PIPELINE_ENV = Path(__file__).parent.parent.parent / "law-pipeline" / ".env"

PII_FIELDS = [
    ("customer_name", "[KUND]"),
    ("customer_email", "[EPOST]"),
    ("customer_phone", "[TELEFON]"),
    ("property_address", "[ADRESS]"),
]


class LLMError(RuntimeError):
    pass


def _read_env_key(name: str, env_file: Path) -> Optional[str]:
    key = os.environ.get(name)
    if key:
        return key
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip()
    return None


PROVIDERS = [
    {
        "name": "deepseek",
        "url": "https://api.deepseek.com/v1/chat/completions",
        "model": "deepseek-chat",
        "key": lambda: _read_env_key("DEEPSEEK_API_KEY", BACKEND_ENV),
    },
    {
        "name": "openrouter",
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "model": "moonshotai/kimi-k2.6",
        "key": lambda: _read_env_key("OPENROUTER_API_KEY", PIPELINE_ENV),
    },
]


def scrub_pii(text: str, case_fields: Dict[str, Any]) -> str:
    out = text or ""
    for field, placeholder in PII_FIELDS:
        val = str(case_fields.get(field) or "").strip()
        if len(val) >= 4:
            out = out.replace(val, placeholder)
    return out


def unscrub_pii(text: str, case_fields: Dict[str, Any]) -> str:
    out = text or ""
    for field, placeholder in PII_FIELDS:
        val = str(case_fields.get(field) or "").strip()
        if val:
            out = out.replace(placeholder, val)
    return out


def _log_call(db, job_id, stage, provider, model, status, error, latency_ms, prompt_text, response_text):
    if db is None:
        return
    from app.models import LLMCall

    try:
        db.add(LLMCall(
            job_id=job_id, stage=stage, provider=provider, model=model,
            status=status, error=error, latency_ms=latency_ms,
            prompt_text=(prompt_text or "")[:50000],
            response_text=(response_text or "")[:50000],
        ))
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[llm] call log failed: {e}")


def chat_json(
    system: str,
    user: str,
    schema: Type[BaseModel],
    *,
    db=None,
    job_id: Optional[str] = None,
    stage: str = "",
    max_tokens: int = 4000,
    timeout: float = 120.0,
) -> Tuple[BaseModel, Dict[str, Any]]:
    """JSON-mode chat across the provider chain, schema-validated.

    Per provider: up to 2 attempts (covers one 5xx/timeout retry OR one
    schema-error reprompt), then the next provider. Raises LLMError when
    all providers are exhausted. Returns (parsed, meta).
    """
    prompt_log = f"[system]\n{system}\n\n[user]\n{user}"
    last_err = "no LLM provider configured"
    for prov in PROVIDERS:
        key = prov["key"]()
        if not key:
            continue
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        for attempt in range(2):
            t0 = time.time()
            try:
                r = httpx.post(
                    prov["url"],
                    json={
                        "model": prov["model"],
                        "messages": messages,
                        "response_format": {"type": "json_object"},
                        "max_tokens": max_tokens,
                    },
                    headers={"Authorization": f"Bearer {key}"},
                    timeout=timeout,
                )
            except httpx.RequestError as e:
                last_err = f"{prov['name']}: {e}"
                _log_call(db, job_id, stage, prov["name"], prov["model"], "error", str(e),
                          int((time.time() - t0) * 1000), prompt_log, None)
                continue
            latency = int((time.time() - t0) * 1000)
            if r.status_code >= 500:
                last_err = f"{prov['name']}: HTTP {r.status_code}"
                _log_call(db, job_id, stage, prov["name"], prov["model"], "error",
                          f"HTTP {r.status_code}: {r.text[:300]}", latency, prompt_log, None)
                continue
            if r.status_code != 200:
                last_err = f"{prov['name']}: HTTP {r.status_code} {r.text[:200]}"
                _log_call(db, job_id, stage, prov["name"], prov["model"], "error",
                          f"HTTP {r.status_code}: {r.text[:300]}", latency, prompt_log, None)
                break
            raw = r.json()["choices"][0]["message"]["content"]
            try:
                parsed = schema.model_validate_json(raw)
            except ValidationError as e:
                _log_call(db, job_id, stage, prov["name"], prov["model"], "error",
                          f"schema: {str(e)[:500]}", latency, prompt_log, raw)
                last_err = f"{prov['name']}: schema validation failed"
                if attempt == 0:
                    messages = messages + [
                        {"role": "assistant", "content": raw},
                        {"role": "user", "content": (
                            "Ditt svar validerade inte mot schemat: "
                            f"{str(e)[:800]}\nSvara igen med endast giltig JSON enligt instruktionerna."
                        )},
                    ]
                    continue
                break
            _log_call(db, job_id, stage, prov["name"], prov["model"], "ok", None, latency, prompt_log, raw)
            return parsed, {"provider": prov["name"], "model": prov["model"], "latency_ms": latency}
    raise LLMError(last_err)
```

- [ ] **Step 3: PII tests pass** `python -m pytest tests/test_pii.py -v`

- [ ] **Step 4: Chain test (monkeypatched httpx)**

`backend/tests/test_llm_chain.py`:
```python
import json

import httpx
import pytest
from pydantic import BaseModel

import app.llm as llm


class Out(BaseModel):
    x: int


class FakeResponse:
    def __init__(self, status_code, content=None, text=""):
        self.status_code = status_code
        self.text = text
        self._content = content

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


def test_fallback_to_second_provider(monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append(url)
        if "deepseek" in url:
            return FakeResponse(500, text="boom")
        return FakeResponse(200, content=json.dumps({"x": 7}))

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    monkeypatch.setattr(llm, "PROVIDERS", [
        {"name": "deepseek", "url": "https://api.deepseek.com/x", "model": "m1", "key": lambda: "k"},
        {"name": "openrouter", "url": "https://openrouter.ai/x", "model": "m2", "key": lambda: "k"},
    ])
    parsed, meta = llm.chat_json("s", "u", Out)
    assert parsed.x == 7
    assert meta["provider"] == "openrouter"
    assert len(calls) == 3  # 2 deepseek attempts + 1 openrouter


def test_schema_reprompt_then_success(monkeypatch):
    responses = [FakeResponse(200, content="not json at all"),
                 FakeResponse(200, content=json.dumps({"x": 1}))]

    def fake_post(url, **kwargs):
        return responses.pop(0)

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    monkeypatch.setattr(llm, "PROVIDERS", [
        {"name": "deepseek", "url": "u", "model": "m", "key": lambda: "k"},
    ])
    parsed, _ = llm.chat_json("s", "u", Out)
    assert parsed.x == 1


def test_all_fail_raises(monkeypatch):
    monkeypatch.setattr(llm.httpx, "post", lambda url, **kw: FakeResponse(500, text="x"))
    monkeypatch.setattr(llm, "PROVIDERS", [
        {"name": "deepseek", "url": "u", "model": "m", "key": lambda: "k"},
    ])
    with pytest.raises(llm.LLMError):
        llm.chat_json("s", "u", Out)
```

Run → PASS (fix until green).

- [ ] **Step 5: Commit** `feat(backend): shared LLM client — provider chain, JSON schema validation, PII scrub, call logging`

---

### Task 3: `rag.py` upgrades — singleton index, search_vault, exclusions

**Files:**
- Modify: `backend/app/rag.py`
- Test: `backend/tests/test_rag_helpers.py`

- [ ] **Step 1: Failing tests**

`backend/tests/test_rag_helpers.py`:
```python
from app.rag import DIR_MAP, MAX_NOTE_CHARS, eligible_notes, note_source_url


def _note(path, chars=100):
    return {"path": path, "title": path, "text": "x" * chars}


def test_eligible_notes_filters_dirs_and_size():
    notes = [
        _note("Lagstiftning/FAL 4 kap 6 §.md".replace(".md", "")),
        _note("Lagstiftning/FAL hela lagen", chars=MAX_NOTE_CHARS + 1),
        _note("ARN/ARN 2023-001"),
        _note("Koncept/Nedsättning"),
    ]
    all_dirs = eligible_notes(notes)
    assert len(all_dirs) == 2  # full law dropped, Koncept never searched
    only_arn = eligible_notes(notes, dirs=["arn"])
    assert [n["path"] for n in only_arn] == ["ARN/ARN 2023-001"]


def test_note_source_url():
    text = '---\ntype: lagrum\nsource_url: "https://lagen.nu/2005:104#K4P6"\n---\n\n# FAL'
    assert note_source_url(text) == "https://lagen.nu/2005:104#K4P6"
    assert note_source_url("# No frontmatter") is None
```

Run → FAIL.

- [ ] **Step 2: Implement in `rag.py`**

Replace the `SEARCH_DIRS` line and the `search_law`/`search_precedents` functions with:

```python
MAX_NOTE_CHARS = 15000

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


def note_source_url(text: str) -> Optional[str]:
    m = SOURCE_URL_RE.search(text[:600])
    return m.group(1).strip() if m else None


def eligible_notes(notes: List[NoteDict], dirs: Optional[List[str]] = None) -> List[NoteDict]:
    prefixes = tuple(DIR_MAP[d] for d in dirs) if dirs else tuple(DIR_MAP.values())
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
                          k: int = 5, min_score: float = 0.0) -> List[NoteDict]:
    notes, index = get_index()
    pool = {n["path"]: n for n in eligible_notes(notes, dirs)}
    scored: List[ScoredNote] = []
    for path, entry in index.items():
        n = pool.get(path)
        if n is None:
            continue
        s = _cosine(q_emb, entry["embedding"])
        if s >= min_score:
            scored.append((s, n))
    scored.sort(key=lambda x: -x[0])
    return [_hit(s, n) for s, n in scored[:k]]


def search_vault(query: str, dirs: Optional[List[str]] = None,
                 k: int = 5, min_score: float = 0.0) -> List[NoteDict]:
    return search_with_embedding(embed_queries([query])[0], dirs=dirs, k=k, min_score=min_score)


def search_law(query: str, k: int = 5) -> List[NoteDict]:
    return search_vault(query, dirs=None, k=k)


def search_precedents(damage_category: str, insurer_decision_text: str = "", k: int = 5) -> List[NoteDict]:
    query = f"skada {damage_category} försäkring"
    if insurer_decision_text:
        query += f" {insurer_decision_text[:200]}"
    return search_vault(query, dirs=["arn"], k=k)
```

Keep `retrieve()` and everything above it unchanged (Voyage batching already single-call for ≤8 queries).

- [ ] **Step 3: Tests pass**; also `python -m pytest tests/ -v` all green; `python -c "from app.rag import search_law"` imports.

- [ ] **Step 4: Commit** `feat(backend): RAG singleton index, dir/threshold search, whole-statute exclusion, source urls`

---

### Task 4: `verify.py` — lagrum normalizer + citation resolver

**Files:**
- Create: `backend/app/verify.py`
- Test: `backend/tests/test_verify.py`

- [ ] **Step 1: Failing tests**

`backend/tests/test_verify.py`:
```python
from app.verify import CitationResolver, normalize_lagrum, verify_citations


def test_normalize_forms():
    assert normalize_lagrum("FAL 4 kap 6 §") == "FAL 4 kap 6 §"
    assert normalize_lagrum("4 kap. 6 § FAL") == "FAL 4 kap 6 §"
    assert normalize_lagrum("36 § avtalslagen (1915:218)") == "Avtalslagen 36 §"
    assert normalize_lagrum("12 kap 18a § JB") == "Jordabalken 12 kap 18 a §"
    assert normalize_lagrum("enligt försäkringsavtalslagen 8 kap 9 §") == "FAL 8 kap 9 §"
    assert normalize_lagrum("Okänd lag 3 §") is None
    assert normalize_lagrum("") is None


def _resolver():
    return CitationResolver(
        vault_titles={"FAL 4 kap 6 §", "Avtalslagen 36 §"},
        law_refs={"FAL 6 kap 1 §"},
        arn_ids={"2018-11707"},
        evidence_ids={"DOC-1", "DOC-2"},
    )


def test_resolver_paths():
    r = _resolver()
    assert r.resolve("doc-2")["kind"] == "evidence"
    assert r.resolve("ARN 2018-11707")["ref"] == "ARN 2018-11707"
    assert r.resolve("4 kap. 6 § FAL")["ref"] == "FAL 4 kap 6 §"
    assert r.resolve("FAL 6 kap 1 §")["kind"] == "lagrum"
    assert r.resolve("ARN 1999-00000") is None
    assert r.resolve("Hittepålagen 99 §") is None


def test_verify_citations_split():
    r = _resolver()
    citations = [
        {"ref": "FAL 4 kap 6 §", "doc_id": "DOC-1"},
        {"ref": "Påhittad lag 1 §", "doc_id": None},
    ]
    verified, flagged = verify_citations(citations, r)
    assert [v["ref"] for v in verified] == ["FAL 4 kap 6 §"]
    assert flagged == ["Påhittad lag 1 §"]
```

Run → FAIL.

- [ ] **Step 2: Create `backend/app/verify.py`**

```python
from __future__ import annotations

import re
from typing import Dict, List, Optional, Set, Tuple

STATUTE_ALIASES = {
    "fal": "FAL",
    "försäkringsavtalslagen": "FAL",
    "försäkringsavtalslag": "FAL",
    "avtalslagen": "Avtalslagen",
    "avtl": "Avtalslagen",
    "skadeståndslagen": "Skadeståndslagen",
    "skl": "Skadeståndslagen",
    "jordabalken": "Jordabalken",
    "jb": "Jordabalken",
    "bostadsrättslagen": "Bostadsrättslagen",
    "brl": "Bostadsrättslagen",
    "konsumentköplagen": "Konsumentköplagen",
    "kkl": "Konsumentköplagen",
    "konsumenttjänstlagen": "Konsumenttjänstlagen",
    "ktjl": "Konsumenttjänstlagen",
    "konsumentförsäkringslagen": "Konsumentförsäkringslagen",
    "konsumentavtalsvillkorslagen": "Konsumentavtalsvillkorslagen",
    "distansavtalslagen": "Distansavtalslagen",
    "trafikskadelagen": "Trafikskadelagen",
    "paketreselagen": "Paketreselagen",
}

ARN_RE = re.compile(r"(?:ARN\s*)?(\d{4}-\d{4,6})")
DOC_RE = re.compile(r"^DOC-\d+$", re.IGNORECASE)
_PRE_RE = re.compile(
    r"(?P<statute>[A-Za-zåäöÅÄÖ]+)\s+(?:(?P<chap>\d+)\s*kap\.?\s+)?(?P<para>\d+\s*[a-z]?)\s*§"
)
_POST_RE = re.compile(
    r"(?:(?P<chap>\d+)\s*kap\.?\s+)?(?P<para>\d+\s*[a-z]?)\s*§\s+(?P<statute>[A-Za-zåäöÅÄÖ]+)"
)


def _canonical(statute: str, chap: Optional[str], para: str) -> str:
    para = re.sub(r"(\d+)\s*([a-z])", r"\1 \2", para.strip())
    if chap:
        return f"{statute} {chap} kap {para} §"
    return f"{statute} {para} §"


def normalize_lagrum(ref: str) -> Optional[str]:
    text = (ref or "").strip()
    if not text:
        return None
    for rx in (_PRE_RE, _POST_RE):
        for m in rx.finditer(text):
            statute = STATUTE_ALIASES.get(m.group("statute").lower())
            if statute:
                return _canonical(statute, m.group("chap"), m.group("para"))
    return None


class CitationResolver:
    def __init__(self, vault_titles: Set[str], law_refs: Set[str],
                 arn_ids: Set[str], evidence_ids: Set[str]):
        self._vault = {t.lower() for t in vault_titles}
        self._laws = {r.lower() for r in law_refs}
        self._arn = set(arn_ids)
        self._evidence = {e.upper() for e in evidence_ids}

    def resolve(self, ref: str) -> Optional[Dict[str, str]]:
        ref = (ref or "").strip()
        if not ref:
            return None
        if DOC_RE.match(ref) and ref.upper() in self._evidence:
            return {"ref": ref.upper(), "kind": "evidence"}
        m = ARN_RE.search(ref)
        if m and m.group(1) in self._arn:
            return {"ref": f"ARN {m.group(1)}", "kind": "arn"}
        norm = normalize_lagrum(ref)
        if norm and (norm.lower() in self._vault or norm.lower() in self._laws):
            return {"ref": norm, "kind": "lagrum"}
        if ref.lower() in self._vault:
            return {"ref": ref, "kind": "vault"}
        return None


def verify_citations(citations: List[dict], resolver: CitationResolver) -> Tuple[List[dict], List[str]]:
    """Split citations into (verified, flagged refs). Each citation: {ref, doc_id?}."""
    verified: List[dict] = []
    flagged: List[str] = []
    seen: Set[str] = set()
    for c in citations:
        ref = (c.get("ref") or "").strip()
        doc_id = (c.get("doc_id") or "").strip()
        hit = resolver.resolve(ref) or (resolver.resolve(doc_id) if doc_id else None)
        if hit:
            out = {"ref": hit["ref"] if hit["kind"] != "evidence" else (ref or hit["ref"]),
                   "kind": hit["kind"], "doc_id": doc_id or None}
            if out["ref"].lower() not in seen:
                seen.add(out["ref"].lower())
                verified.append(out)
        elif ref and ref.lower() not in seen:
            seen.add(ref.lower())
            flagged.append(ref)
    return verified, flagged


def build_resolver(db, evidence_ids: Set[str]) -> CitationResolver:
    from app.models import ARNDecision, LawSection
    from app.rag import get_index

    notes, _ = get_index()
    vault_titles = {n["title"] for n in notes}
    arn_ids = {n["title"].replace("ARN ", "") for n in notes if n["path"].startswith("ARN/")}
    law_refs = {row[0] for row in db.query(LawSection.full_reference).all() if row[0]}
    arn_ids |= {row[0] for row in db.query(ARNDecision.id).all() if row[0]}
    return CitationResolver(vault_titles, law_refs, arn_ids, evidence_ids)
```

- [ ] **Step 3: Tests pass** (`test_normalize_forms` drives regex fixes — e.g. `finditer` to skip the leading "enligt").

- [ ] **Step 4: Commit** `feat(backend): citation verifier — lagrum normalization + vault/DB resolution`

---

### Task 5: `draft_ai.py` — 4-stage pipeline

**Files:**
- Create: `backend/app/draft_ai.py`
- Test: `backend/tests/test_draft_helpers.py`

- [ ] **Step 1: Failing tests for pure helpers**

`backend/tests/test_draft_helpers.py`:
```python
from app.draft_ai import DraftPlan, budget_evidence, fallback_plan


def test_fallback_plan_always_valid():
    plan = fallback_plan({"damage_category": "Vattenskada", "damage_description": "Läcka i köket", "insurer_reason": "åldersavdrag 80%"})
    assert isinstance(plan, DraftPlan)
    assert 1 <= len(plan.arguments) <= 4
    assert all(a.queries for a in plan.arguments)


def _hit(path, score, chars=3000):
    return {"path": path, "title": path.split("/")[-1], "score": score, "text": "x" * chars, "source_url": None}


def test_budget_evidence_dedupes_caps_and_numbers():
    per_query = [
        [_hit("Lagstiftning/A", 0.9), _hit("Lagstiftning/B", 0.8)],
        [_hit("Lagstiftning/A", 0.7), _hit("ARN/C", 0.6)],
    ]
    docs = budget_evidence(per_query, max_docs=2, max_chars=100)
    assert [d["doc_id"] for d in docs] == ["DOC-1", "DOC-2"]
    assert [d["path"] for d in docs] == ["Lagstiftning/A", "Lagstiftning/B"]  # dedupe kept best score, cap 2
    assert all(len(d["text"]) <= 100 for d in docs)
```

Run → FAIL.

- [ ] **Step 2: Create `backend/app/draft_ai.py`**

```python
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.llm import LLMError, PIPELINE_VERSION, chat_json, scrub_pii, unscrub_pii
from app.models import Case, DraftJob, ResponseDraft
from app.rag import DIR_MAP, embed_queries, search_with_embedding
from app.verify import build_resolver, verify_citations

MIN_SCORE = 0.35
MAX_DOCS = 12
MAX_DOC_CHARS = 2500
MAX_QUERIES = 6


class PlanArgument(BaseModel):
    claim: str
    queries: List[str] = Field(min_length=1, max_length=3)
    dataset_types: List[str] = []


class DraftPlan(BaseModel):
    arguments: List[PlanArgument] = Field(min_length=1, max_length=4)
    missing_info: List[str] = []


class DraftCitation(BaseModel):
    ref: str
    doc_id: Optional[str] = None


class DraftLetter(BaseModel):
    subject: str
    body_markdown: str


class DraftOutput(BaseModel):
    strategy_note: str
    letter: DraftLetter
    citations: List[DraftCitation] = []
    demands: List[str] = []
    deadline_days: int = 14


PLAN_SYSTEM = """Du är en svensk försäkringsjurist på Swiftclaim. Planera argumentationen för ett brev till försäkringsbolaget som kräver högre ersättning.

Tillgängliga kunskapskällor (dataset_types):
- lagstiftning: svenska lagparagrafer (FAL, Avtalslagen, Jordabalken m.fl.)
- arn: ARN-nämndbeslut (prejudikat)
- praxis: domstolspraxis (NJA m.m.)
- villkor: försäkringsbolagens villkorstexter
- forarbeten: propositioner och förarbeten
- vagledning: myndighetsvägledning

Svara endast med JSON:
{
  "arguments": [
    {"claim": "<juridiskt argument på svenska>",
     "queries": ["<sökfråga på svenska>", ...],   // 1-3 per argument
     "dataset_types": ["lagstiftning", "arn", ...]}
  ],
  "missing_info": ["<uppgift som saknas>", ...]
}
Max 4 argument. Max 6 sökfrågor totalt. Välj dataset_types som passar argumentet."""


DRAFT_SYSTEM = """Du är en erfaren svensk försäkringsjurist på Swiftclaim. Skriv ett professionellt brev till försäkringsbolaget som bestrider deras beslut och kräver rätt ersättning.

REGLER:
- Grunda VARJE juridiskt påstående i de numrerade källdokumenten [DOC-n] eller i exakta lagrum.
- Citera lagrum exakt (t.ex. "FAL 4 kap 6 §") och ARN-beslut med nummer (t.ex. "ARN 2018-11707").
- Hitta ALDRIG på lagrum, rättsfall eller villkor som inte finns i källorna.
- Kunden heter [KUND] — använd platshållaren exakt så i brevet.
- Professionell men bestämd ton. Konkreta yrkanden. Svarsfrist.

Svara endast med JSON:
{
  "strategy_note": "<intern strateginot på svenska>",
  "letter": {"subject": "<ärenderubrik>", "body_markdown": "<komplett brevtext på svenska>"},
  "citations": [{"ref": "<lagrum eller ARN-nummer>", "doc_id": "<DOC-n eller null>"}],
  "demands": ["<yrkande>", ...],
  "deadline_days": 14
}
Lista i citations VARJE lagrum och ARN-beslut som nämns i brevet."""


REPAIR_SYSTEM = """Du är en svensk försäkringsjurist. Brevet nedan innehåller hänvisningar som INTE kunde verifieras mot vår rättsdatabas. Skriv om brevet: ersätt varje overifierad hänvisning med en verifierad källa från listan, eller ta bort påståendet helt. Ändra inget annat.

Svara endast med JSON i samma schema som tidigare:
{"strategy_note": "...", "letter": {"subject": "...", "body_markdown": "..."}, "citations": [{"ref": "...", "doc_id": null}], "demands": ["..."], "deadline_days": 14}"""


def case_fields(case: Case) -> Dict[str, Any]:
    return {
        "customer_name": case.customer_name,
        "customer_email": case.customer_email,
        "customer_phone": case.customer_phone,
        "property_address": case.property_address,
        "insurance_company": case.insurance_company,
        "insurance_policy_number": case.insurance_policy_number,
        "damage_category": case.damage_category,
        "damage_description": case.damage_description or "",
        "damage_date": case.damage_date,
        "claim_amount": case.claim_amount,
        "insurer_decision": case.insurer_decision,
        "insurer_amount": case.insurer_amount,
        "insurer_reason": case.insurer_reason or "",
    }


def case_block(fields: Dict[str, Any]) -> str:
    raw = "\n".join([
        "ÄRENDE:",
        f"Kund: {fields['customer_name'] or 'okänd'}",
        f"Försäkringsbolag: {fields['insurance_company'] or 'okänt'}",
        f"Försäkringsnummer: {fields['insurance_policy_number'] or 'okänt'}",
        f"Typ av skada: {fields['damage_category'] or 'okänd'}",
        f"Skadebeskrivning: {fields['damage_description'][:1500]}",
        f"Skadedatum: {fields['damage_date'] or 'okänt'}",
        f"Yrkat belopp: {fields['claim_amount'] or 'ej specificerat'} kr",
        f"Bolagets beslut: {fields['insurer_decision'] or 'okänt'}",
        f"Bolagets motivering: {fields['insurer_reason'][:800] or 'ingen angiven'}",
        f"Erbjudet belopp: {fields['insurer_amount'] or 'ej specificerat'} kr",
    ])
    return scrub_pii(raw, fields)


def fallback_plan(fields: Dict[str, Any]) -> DraftPlan:
    queries = [f"{fields.get('damage_category', '')} {fields.get('damage_description', '')[:200]}".strip()]
    if fields.get("insurer_reason"):
        queries.append(f"nedsättning ersättning {fields['insurer_reason'][:150]}")
    else:
        queries.append(f"försäkringsersättning {fields.get('damage_category', '')}")
    return DraftPlan(arguments=[PlanArgument(
        claim="Rätt till full ersättning enligt försäkringsavtalet och FAL",
        queries=queries[:3],
        dataset_types=list(DIR_MAP.keys()),
    )])


def budget_evidence(per_query_hits: List[List[dict]], max_docs: int = MAX_DOCS,
                    max_chars: int = MAX_DOC_CHARS) -> List[dict]:
    best: Dict[str, dict] = {}
    for hits in per_query_hits:
        for h in hits:
            cur = best.get(h["path"])
            if cur is None or h["score"] > cur["score"]:
                best[h["path"]] = h
    ranked = sorted(best.values(), key=lambda h: -h["score"])[:max_docs]
    return [{
        "doc_id": f"DOC-{i + 1}",
        "path": h["path"],
        "title": h["title"],
        "score": h["score"],
        "source_url": h.get("source_url"),
        "text": h["text"][:max_chars],
    } for i, h in enumerate(ranked)]


def evidence_block(evidence: List[dict]) -> str:
    parts = []
    for d in evidence:
        src = f" (källa: {d['source_url']})" if d.get("source_url") else ""
        parts.append(f"[{d['doc_id']}] {d['title']}{src}\n{d['text']}")
    return "\n\n---\n\n".join(parts) if parts else "(inga källdokument hittades)"


def _set_stage(db: Session, job: DraftJob, status: str, key: str, snapshot: Any) -> None:
    job.status = status
    job.stages = {**(job.stages or {}), key: snapshot}
    job.updated_at = datetime.utcnow()
    db.commit()


def run_draft_job(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.query(DraftJob).filter(DraftJob.id == job_id).first()
        if not job:
            return
        case = db.query(Case).filter(Case.id == job.case_id).first()
        if not case:
            job.status, job.error = "failed", "case not found"
            db.commit()
            return
        try:
            _run_stages(db, job, case)
        except LLMError as e:
            job.status, job.error = "failed", f"LLM providers exhausted: {e}"
            db.commit()
        except Exception as e:
            job.status, job.error = "failed", f"{type(e).__name__}: {e}"
            db.commit()
    finally:
        db.close()


def _run_stages(db: Session, job: DraftJob, case: Case) -> None:
    fields = case_fields(case)
    request = (job.stages or {}).get("request", {})

    # 1 PLAN
    job.status = "planning"
    db.commit()
    plan_degraded = False
    try:
        plan, _ = chat_json(PLAN_SYSTEM, case_block(fields), DraftPlan,
                            db=db, job_id=job.id, stage="draft.plan", max_tokens=1200)
    except LLMError:
        plan, plan_degraded = fallback_plan(fields), True
    _set_stage(db, job, "planning", "plan", {"degraded": plan_degraded, **plan.model_dump()})

    # 2 RETRIEVE
    job.status = "retrieving"
    db.commit()
    tasks: List[Tuple[str, Optional[List[str]]]] = []
    for arg in plan.arguments:
        dirs = [d for d in arg.dataset_types if d in DIR_MAP] or None
        for q in arg.queries:
            if len(tasks) < MAX_QUERIES and q.strip():
                tasks.append((scrub_pii(q, fields), dirs))
    embeddings = embed_queries([q for q, _ in tasks])
    per_query = [search_with_embedding(emb, dirs=dirs, k=4, min_score=MIN_SCORE)
                 for emb, (_, dirs) in zip(embeddings, tasks)]
    evidence = budget_evidence(per_query)
    _set_stage(db, job, "retrieving", "retrieval", {
        "queries": [q for q, _ in tasks],
        "docs": [{k: d[k] for k in ("doc_id", "path", "title", "score", "source_url")} for d in evidence],
    })

    # 3 DRAFT
    job.status = "drafting"
    db.commit()
    user_msg = "\n\n".join([
        case_block(fields),
        "ARGUMENTPLAN:\n" + "\n".join(f"- {a.claim}" for a in plan.arguments),
        "KÄLLDOKUMENT:\n\n" + evidence_block(evidence),
        f"Strategi: {request.get('strategy', 'maximize_payout')}",
        f"Ytterligare kontext: {scrub_pii(request.get('additional_context') or 'ingen', fields)}",
    ])
    out, meta = chat_json(DRAFT_SYSTEM, user_msg, DraftOutput,
                          db=db, job_id=job.id, stage="draft.write")
    _set_stage(db, job, "drafting", "draft", {"model": meta["model"], "subject": out.letter.subject})

    # 4 VERIFY (+ repair) + SAVE
    job.status = "verifying"
    db.commit()
    evidence_ids = {d["doc_id"] for d in evidence}
    resolver = build_resolver(db, evidence_ids)
    verified, flagged = verify_citations([c.model_dump() for c in out.citations], resolver)
    repaired = False
    if flagged:
        valid_refs = [v["ref"] for v in verified] + [f"{d['doc_id']}: {d['title']}" for d in evidence]
        repair_msg = "\n\n".join([
            "BREV:\n" + out.letter.body_markdown,
            "OVERIFIERADE HÄNVISNINGAR:\n" + "\n".join(f"- {f}" for f in flagged),
            "VERIFIERADE KÄLLOR:\n" + "\n".join(f"- {r}" for r in valid_refs),
        ])
        try:
            out, meta = chat_json(REPAIR_SYSTEM, repair_msg, DraftOutput,
                                  db=db, job_id=job.id, stage="draft.repair")
            verified, flagged = verify_citations([c.model_dump() for c in out.citations], resolver)
            repaired = True
        except LLMError:
            pass  # flag-only path: draft saved as needs_review below
    _set_stage(db, job, "verifying", "verify", {
        "verified": [v["ref"] for v in verified], "flagged": flagged, "repaired": repaired,
    })

    force_review = not evidence
    letter_text = unscrub_pii(f"Ärende: {out.letter.subject}\n\n{out.letter.body_markdown}", fields)
    prev = db.query(ResponseDraft).filter(ResponseDraft.case_id == case.id) \
        .order_by(ResponseDraft.version.desc()).first()
    draft = ResponseDraft(
        case_id=case.id,
        version=(prev.version + 1) if prev else 1,
        strategy=out.strategy_note,
        draft_text=letter_text,
        citations_used=[v["ref"] for v in verified],
        flagged_citations=flagged,
        evidence=[{k: d[k] for k in ("doc_id", "path", "title", "score", "source_url")} for d in evidence],
        model_used=meta["model"],
        job_id=job.id,
        status="needs_review" if (flagged or force_review) else "draft",
    )
    db.add(draft)
    case.status = "draft"
    case.updated_at = datetime.utcnow()
    db.flush()
    job.status = "done"
    job.draft_id = draft.id
    job.pipeline_version = PIPELINE_VERSION
    job.updated_at = datetime.utcnow()
    db.commit()


def create_job(db: Session, case_id: str, strategy: str, additional_context: str) -> DraftJob:
    job = DraftJob(
        id=uuid.uuid4().hex,
        case_id=case_id,
        status="queued",
        stages={"request": {"strategy": strategy, "additional_context": additional_context}},
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job
```

- [ ] **Step 3: Helper tests pass**; full `python -m pytest tests/ -v` green.

- [ ] **Step 4: Commit** `feat(backend): 4-stage draft pipeline — plan, retrieve, draft, verify+repair`

---

### Task 6: `qa_ai.py` — vault Q&A

**Files:**
- Create: `backend/app/qa_ai.py`

- [ ] **Step 1: Create `backend/app/qa_ai.py`**

```python
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.draft_ai import DraftCitation, case_block, case_fields
from app.llm import LLMError, chat_json, scrub_pii, unscrub_pii
from app.models import Case
from app.rag import search_vault
from app.verify import build_resolver, verify_citations

MIN_SCORE = 0.35


class QAOutput(BaseModel):
    answer_markdown: str
    citations: List[DraftCitation] = []


ASK_SYSTEM = """Du är en svensk försäkringsjurist på Swiftclaim. Besvara frågan med stöd av ENDAST de numrerade källdokumenten nedan.

REGLER:
- Grunda varje påstående i källorna; hänvisa med exakta lagrum (t.ex. "FAL 4 kap 6 §") eller ARN-nummer.
- Om källorna inte räcker för att besvara frågan: säg det tydligt i svaret.
- Hitta aldrig på lagrum eller rättsfall.

Svara endast med JSON:
{"answer_markdown": "<svar på svenska>", "citations": [{"ref": "<lagrum/ARN-nummer>", "doc_id": "<DOC-n eller null>"}]}"""


def ask(db: Session, question: str, case: Optional[Case] = None) -> Dict[str, Any]:
    fields = case_fields(case) if case else {}
    q = scrub_pii(question, fields) if case else question
    rag_query = f"{fields.get('damage_category', '')} {q}".strip() if case else q

    hits = search_vault(rag_query, k=8, min_score=MIN_SCORE)
    if not hits:
        return {
            "answer_markdown": "Hittade inga relevanta källor i kunskapsbasen för frågan. Formulera gärna om frågan eller ange mer detaljer.",
            "sources": [], "unverified_refs": [], "model_used": None,
        }

    evidence = [{
        "doc_id": f"DOC-{i + 1}", "path": h["path"], "title": h["title"],
        "score": h["score"], "source_url": h.get("source_url"), "text": h["text"][:2000],
    } for i, h in enumerate(hits)]

    docs = "\n\n---\n\n".join(
        f"[{d['doc_id']}] {d['title']}" + (f" (källa: {d['source_url']})" if d["source_url"] else "") + f"\n{d['text']}"
        for d in evidence
    )
    parts = []
    if case:
        parts.append(case_block(fields))
    parts.append(f"FRÅGA:\n{q}")
    parts.append(f"KÄLLDOKUMENT:\n\n{docs}")

    out, meta = chat_json(ASK_SYSTEM, "\n\n".join(parts), QAOutput,
                          db=db, stage="ask", max_tokens=1500)

    resolver = build_resolver(db, {d["doc_id"] for d in evidence})
    verified, flagged = verify_citations([c.model_dump() for c in out.citations], resolver)

    by_doc = {d["doc_id"]: d for d in evidence}
    by_title = {d["title"].lower(): d for d in evidence}
    sources = []
    for v in verified:
        doc = by_doc.get((v.get("doc_id") or "").upper()) or by_title.get(v["ref"].lower())
        sources.append({
            "ref": v["ref"],
            "title": doc["title"] if doc else v["ref"],
            "path": doc["path"] if doc else "",
            "score": doc["score"] if doc else 0.0,
            "source_url": doc["source_url"] if doc else None,
        })

    return {
        "answer_markdown": unscrub_pii(out.answer_markdown, fields),
        "sources": sources,
        "unverified_refs": flagged,
        "model_used": meta["model"],
    }
```

- [ ] **Step 2: Import check** `python -c "from app.qa_ai import ask"`; full pytest green.

- [ ] **Step 3: Commit** `feat(backend): vault Q&A with verified references`

---

### Task 7: API endpoints + intake refactor onto llm.py

**Files:**
- Modify: `backend/app/main.py`, `backend/app/intake_ai.py`

- [ ] **Step 1: main.py — replace draft endpoint, add jobs + ask, startup sweep**

Remove `DRAFT_SYSTEM_PROMPT` and the whole `generate_draft` function body (lines ~258-406). Remove `import httpx` if now unused and the `from app.intake_ai import ... LLM_URL, CHAT_MODEL, _get_llm_key` extras (keep `analyze as run_intake_analysis`). Add imports:

```python
from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from app.models import Case, ARNDecision, LawSection as LawSectionModel, ResponseDraft, KnowledgeNote, DraftJob
from app.schemas import (..., DraftJobOut, AskRequest, AskOut)
from app.draft_ai import create_job, run_draft_job
from app.qa_ai import ask as run_ask
from app.llm import LLMError
```

In `startup()` after `_seed_laws(db)`:
```python
        stuck = db.query(DraftJob).filter(DraftJob.status.notin_(["done", "failed"]))
        stuck.update({"status": "failed", "error": "server restarted"}, synchronize_session=False)
        db.commit()
```

New endpoints (replace old `/api/draft` POST):
```python
@app.post("/api/draft", status_code=202)
def start_draft(req: DraftRequest, background: BackgroundTasks, db: Session = Depends(get_db)):
    case = db.query(Case).filter(Case.id == req.case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")
    job = create_job(db, req.case_id, req.strategy, req.additional_context)
    background.add_task(run_draft_job, job.id)
    return {"job_id": job.id, "status": job.status}


def _job_out(db: Session, job: DraftJob) -> DraftJobOut:
    draft = db.query(ResponseDraft).filter(ResponseDraft.id == job.draft_id).first() if job.draft_id else None
    out = DraftJobOut.model_validate(job)
    out.draft = ResponseDraftOut.model_validate(draft) if draft else None
    return out


@app.get("/api/draft-jobs/{job_id}", response_model=DraftJobOut)
def get_draft_job(job_id: str, db: Session = Depends(get_db)):
    job = db.query(DraftJob).filter(DraftJob.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    return _job_out(db, job)


@app.get("/api/draft-jobs", response_model=Optional[DraftJobOut])
def get_latest_draft_job(case_id: str, db: Session = Depends(get_db)):
    job = db.query(DraftJob).filter(DraftJob.case_id == case_id) \
        .order_by(DraftJob.created_at.desc()).first()
    return _job_out(db, job) if job else None


@app.post("/api/ask", response_model=AskOut)
def ask_endpoint(req: AskRequest, db: Session = Depends(get_db)):
    case = db.query(Case).filter(Case.id == req.case_id).first() if req.case_id else None
    if req.case_id and not case:
        raise HTTPException(404, "Case not found")
    try:
        return run_ask(db, req.question, case)
    except LLMError as e:
        raise HTTPException(503, f"AI-tjänsten är inte tillgänglig just nu: {e}")
```

- [ ] **Step 2: intake_ai.py — use shared client**

Remove `LLM_URL`, `CHAT_MODEL`, `_get_llm_key`, `_llm_json`, and the `httpx`/`os`/`Path` imports they needed. Add:

```python
from pydantic import BaseModel

from app.llm import LLMError, chat_json


class CategorizeOut(BaseModel):
    category: str


class AssessOut(BaseModel):
    strength: str
    summary: str = ""
    key_arguments: list[str] = []
    missing_info: list[str] = []
```

`categorize()` body becomes:
```python
    try:
        out, _ = chat_json(CATEGORIZE_SYSTEM, user, CategorizeOut, stage="intake.categorize", max_tokens=100)
        if out.category in CATEGORIES:
            return {"category": out.category, "degraded": False}
    except LLMError:
        pass
    return {"category": hint if hint in CATEGORIES else keyword_category(description), "degraded": True}
```

`assess()` LLM call becomes:
```python
    try:
        out, _ = chat_json(ASSESS_SYSTEM, "\n\n".join(parts), AssessOut, stage="intake.assess", max_tokens=1200)
        if out.strength in ("stark", "medel", "svag"):
            return {
                "strength": out.strength,
                "summary": out.summary[:1200],
                "key_arguments": [str(a) for a in out.key_arguments][:6],
                "missing_info": [str(m) for m in out.missing_info][:6],
                "degraded": False,
            }
    except LLMError:
        pass
```
(keep the existing degraded fallback return).

- [ ] **Step 3: Verify** `python -c "from app.main import app"`; full pytest green; boot `python run.py` briefly and `curl -s localhost:8000/api/status`.

- [ ] **Step 4: Commit** `feat(backend): async draft jobs, /api/ask, intake on shared LLM client`

---

### Task 8: `os/api.js` — job polling + ask

**Files:**
- Modify: `os/api.js`

- [ ] **Step 1: apiFetch timeout option**

Replace `apiFetch` with:
```js
  async function apiFetch(path, options = {}) {
    if (!(await isAvailable())) return null;
    const { timeoutMs = 15000, ...rest } = options;
    try {
      const r = await fetch(`${API_BASE}${path}`, {
        headers: { "Content-Type": "application/json", ...rest.headers },
        signal: timeoutSignal(timeoutMs),
        ...rest,
      });
      if (!r.ok) return null;
      return r.json();
    } catch {
      return null;
    }
  }
```

- [ ] **Step 2: Replace `generateDraft` and add job/ask functions**

```js
    /**
     * Start a draft job and poll it to completion.
     * onProgress(status) is called on every poll tick.
     * Resolves to the finished job ({status, draft, error}) or null.
     */
    async generateDraft(caseItem, onProgress) {
      await api.importCase(caseItem);
      const start = await apiFetch("/draft", {
        method: "POST",
        body: JSON.stringify({ case_id: caseItem.id }),
      });
      if (!start || !start.job_id) return null;
      return api.pollDraftJob(start.job_id, onProgress);
    },

    async pollDraftJob(jobId, onProgress) {
      const deadline = Date.now() + 8 * 60 * 1000;
      while (Date.now() < deadline) {
        const job = await apiFetch(`/draft-jobs/${jobId}`);
        if (job) {
          if (onProgress) onProgress(job.status);
          if (job.status === "done" || job.status === "failed") return job;
        }
        await new Promise((resolve) => setTimeout(resolve, 3000));
      }
      return { id: jobId, status: "timeout" };
    },

    async getLatestDraftJob(caseId) {
      return apiFetch(`/draft-jobs?case_id=${encodeURIComponent(caseId)}`);
    },

    /**
     * Ask the legal knowledge base a question, optionally scoped to a case.
     */
    async ask(question, caseId) {
      return apiFetch("/ask", {
        method: "POST",
        body: JSON.stringify({ question, case_id: caseId || null }),
        timeoutMs: 90000,
      });
    },
```

- [ ] **Step 3: Commit** `feat(os): api bridge — draft job polling, ask endpoint, per-call timeouts`

---

### Task 9: OS UI — progress, citations, ask boxes

**Files:**
- Modify: `os/app.js`, `os/index.html`, `os/styles.css`

- [ ] **Step 1: app.js — case panel HTML (in the `legal-research` section, after `legal-actions` div, `os/app.js:1018`)**

```js
            <div class="ask-box">
              <input id="askInput" type="search" placeholder="Fråga juridiken om ärendet, t.ex. 'Kan åldersavdraget ifrågasättas?'" />
              <button class="secondary" id="askBtn" type="button">Fråga</button>
            </div>
            <div id="legalResults" class="legal-results"></div>
```
(replaces the bare `legalResults` div).

- [ ] **Step 2: app.js — replace draft button handler in `bindLegalResearch` and add ask handler**

```js
    // Generate draft button — async job with stage progress
    const DRAFT_STAGES = {
      queued: "Köad...",
      planning: "Planerar argument...",
      retrieving: "Söker rättskällor...",
      drafting: "Skriver utkast...",
      verifying: "Verifierar källor...",
    };
    document.getElementById("generateDraftBtn")?.addEventListener("click", async () => {
      const resultsEl = document.getElementById("legalResults");
      resultsEl.innerHTML = '<p class="muted draft-progress">Startar utkastjobb...</p>';
      const job = await window.SwiftclaimAPI.generateDraft(item, (status) => {
        const label = DRAFT_STAGES[status];
        if (label) resultsEl.innerHTML = `<p class="muted draft-progress">${label}</p>`;
      });
      if (!job) {
        resultsEl.innerHTML = '<p class="muted">Kunde inte starta utkastjobbet. Kör <code>python backend/run.py</code>.</p>';
        return;
      }
      if (job.status === "failed") {
        resultsEl.innerHTML = `<p class="muted">Utkastet misslyckades: ${escapeHtml(job.error || "okänt fel")}</p>`;
        return;
      }
      if (job.status === "timeout") {
        resultsEl.innerHTML = '<p class="muted">Jobbet tar längre än väntat — öppna ärendet igen om en stund.</p>';
        return;
      }
      resultsEl.innerHTML = renderDraftResult(job.draft || {});
    });

    // Ask button — case-scoped question
    const askBtn = document.getElementById("askBtn");
    const askInput = document.getElementById("askInput");
    if (askBtn && askInput) {
      askBtn.addEventListener("click", async () => {
        const question = askInput.value.trim();
        if (!question) return;
        const resultsEl = document.getElementById("legalResults");
        resultsEl.innerHTML = '<p class="muted">Söker svar i kunskapsbasen...</p>';
        const data = await window.SwiftclaimAPI.ask(question, item.id);
        resultsEl.innerHTML = data ? renderAnswer(data) : '<p class="muted">Kunde inte få svar. Kontrollera att backend körs.</p>';
      });
      askInput.addEventListener("keydown", (e) => { if (e.key === "Enter") askBtn.click(); });
    }
```

- [ ] **Step 3: app.js — replace `renderDraftResult` and add `renderAnswer` + `renderSourceList`**

```js
  function renderSourceList(sources) {
    if (!sources || !sources.length) return "";
    return `<ul class="source-list">${sources.map((s) => `
      <li>
        <span class="badge ${String(s.path || s.ref).startsWith("ARN") ? "precedent" : "statute"}">${escapeHtml(s.ref)}</span>
        ${s.source_url ? `<a href="${escapeHtml(s.source_url)}" target="_blank" rel="noopener">lagen.nu ↗</a>` : ""}
        ${s.score ? `<span class="muted score">${Math.round(s.score * 100)}%</span>` : ""}
      </li>`).join("")}</ul>`;
  }

  function renderAnswer(data) {
    return `
      <div class="answer-card">
        <h4>Svar</h4>
        <pre class="draft-text">${escapeHtml(data.answer_markdown || "")}</pre>
        ${data.sources?.length ? `<h4>Källor</h4>${renderSourceList(data.sources)}` : ""}
        ${data.unverified_refs?.length ? `
          <p class="flagged-warning">⚠ Overifierade hänvisningar: ${data.unverified_refs.map(escapeHtml).join(", ")}</p>` : ""}
      </div>
    `;
  }

  function renderDraftResult(draft) {
    const flagged = draft.flagged_citations || [];
    const evidence = draft.evidence || [];
    const citations = draft.citations_used || [];
    return `
      <div class="results-count">Juridiskt utkast genererat (v${draft.version || 1}${draft.model_used ? ` · ${escapeHtml(draft.model_used)}` : ""})</div>
      ${draft.status === "needs_review" ? `
        <div class="needs-review-banner">⚠ Kräver manuell granskning${flagged.length ? ` — overifierade hänvisningar: ${flagged.map(escapeHtml).join(", ")}` : " — inga källor hittades"}</div>` : ""}
      ${draft.strategy ? `
        <div class="draft-section">
          <h4>Strategi</h4>
          <pre class="draft-text">${escapeHtml(draft.strategy)}</pre>
        </div>` : ""}
      <div class="draft-section">
        <h4>Brevutkast</h4>
        <pre class="draft-text">${escapeHtml(draft.draft_text || "")}</pre>
      </div>
      ${citations.length ? `
        <div class="draft-section">
          <h4>Verifierade referenser</h4>
          <ul>${citations.map((c) => `<li>✓ ${escapeHtml(c)}</li>`).join("")}</ul>
        </div>` : ""}
      ${evidence.length ? `
        <div class="draft-section">
          <h4>Källunderlag</h4>
          ${renderSourceList(evidence.map((d) => ({ ref: d.title, path: d.path, score: d.score, source_url: d.source_url })))}
        </div>` : ""}
    `;
  }
```

- [ ] **Step 4: index.html — ask box in Knowledge view (above `vaultSearchInput` block, `os/index.html:297-303`)**

```html
              <div class="ask-box">
                <input id="knowledgeAskInput" type="search" placeholder="Fråga kunskapsbasen, t.ex. 'När får bolaget göra åldersavdrag?'" style="width:100%" />
                <button class="secondary" id="knowledgeAskBtn" type="button">Fråga</button>
              </div>
              <div id="knowledgeAskResult"></div>
```

- [ ] **Step 5: app.js — bind Knowledge ask in `renderKnowledge()` (next to the vault search binding, `os/app.js:1552`)**

```js
    const askKBtn = document.getElementById("knowledgeAskBtn");
    const askKInput = document.getElementById("knowledgeAskInput");
    if (askKBtn && askKInput) {
      askKBtn.onclick = async () => {
        const question = askKInput.value.trim();
        if (!question) return;
        const resultEl = document.getElementById("knowledgeAskResult");
        resultEl.innerHTML = '<p class="muted">Söker svar i kunskapsbasen...</p>';
        const data = await window.SwiftclaimAPI.ask(question);
        resultEl.innerHTML = data ? renderAnswer(data) : '<p class="muted">Kunde inte få svar. Kör <code>python backend/run.py</code>.</p>';
      };
      askKInput.addEventListener("keydown", (e) => { if (e.key === "Enter") askKBtn.click(); });
    }
```

- [ ] **Step 6: styles.css — append**

```css
/* ── Draft v2 + Q&A ─────────────────────────────────────────── */
.ask-box {
  display: flex;
  gap: 8px;
  margin: 10px 0;
}
.ask-box input {
  flex: 1;
}
.answer-card {
  background: var(--surface-alt, #f6f8fb);
  border: 1px solid var(--border, #dbe2ef);
  border-radius: 10px;
  padding: 14px;
  margin-top: 10px;
}
.source-list {
  list-style: none;
  padding: 0;
  margin: 6px 0;
}
.source-list li {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
}
.source-list a {
  font-size: 0.85rem;
}
.needs-review-banner {
  background: #fdf3d7;
  border: 1px solid #e8c668;
  border-radius: 8px;
  padding: 10px 12px;
  margin: 10px 0;
  font-weight: 600;
}
.flagged-warning {
  color: #9a6700;
  font-weight: 600;
}
.draft-progress {
  animation: pulse 1.6s ease-in-out infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.45; }
}
```

- [ ] **Step 7: Manual check** — open `os/index.html`, case detail renders, no console errors (backend may be down; buttons degrade with the offline message).

- [ ] **Step 8: Commit** `feat(os): draft job progress, verified/flagged citations, ask UI`

---

### Task 10: Evals

**Files:**
- Create: `backend/evals/golden_cases.json`, `backend/evals/run_evals.py`, `backend/evals/results/.gitkeep`

- [ ] **Step 1: Golden set**

`backend/evals/golden_cases.json` — 10 cases. Full content:
```json
[
  {"name": "vattenskada-aldersavdrag", "damage_category": "Vattenskada", "damage_description": "Diskmaskinen läckte och vatten rann ut under köksgolvet. Parkettgolv och underliggande spånskiva behöver bytas på 22 kvm. Bolaget gjorde åldersavdrag på 60% eftersom golvet var 18 år gammalt.", "insurance_company": "Folksam", "claim_amount": 180000, "insurer_decision": "partial", "insurer_amount": 72000, "insurer_reason": "Åldersavdrag enligt villkorens tabell, golv äldre än 15 år ersätts med 40% av återanskaffningsvärdet.", "expected_refs": ["FAL 6 kap 1 §", "FAL 6 kap 2 §"]},
  {"name": "brand-aktsamhetskrav", "damage_category": "Brand- eller rökskada", "damage_description": "Brand i köket när matolja antändes på spisen. Bolaget nekar ersättning helt med hänvisning till grov vårdslöshet eftersom spisen lämnades obevakad i några minuter.", "insurance_company": "If", "claim_amount": 450000, "insurer_decision": "denied", "insurer_amount": 0, "insurer_reason": "Grov vårdslöshet: spis lämnad utan uppsikt.", "expected_refs": ["FAL 4 kap 5 §", "FAL 4 kap 9 §"]},
  {"name": "storm-tak", "damage_category": "Stormskada", "damage_description": "Storm rev bort takpannor och delar av underlagstaket på villan. Bolaget hävdar bristande underhåll och sätter ned ersättningen med 50%.", "insurance_company": "Länsförsäkringar", "claim_amount": 220000, "insurer_decision": "partial", "insurer_amount": 110000, "insurer_reason": "Taket var 35 år gammalt och underhåll eftersatt.", "expected_refs": ["FAL 4 kap 6 §", "FAL 6 kap 1 §"]},
  {"name": "inbrott-vardering", "damage_category": "Stöld- eller inbrottsskada", "damage_description": "Inbrott i villan, stöld av elektronik, smycken och kontanter. Bolaget värderar smyckena till en tredjedel av inköpspris utan motivering.", "insurance_company": "Trygg-Hansa", "claim_amount": 95000, "insurer_decision": "partial", "insurer_amount": 41000, "insurer_reason": "Schablonvärdering av smycken.", "expected_refs": ["FAL 6 kap 1 §"]},
  {"name": "mogel-undantag", "damage_category": "Mögel eller fuktskada", "damage_description": "Fukt och mögel upptäcktes i badrummets vägg vid renovering. Bolaget nekar med hänvisning till undantag för långsamt verkande fukt.", "insurance_company": "Folksam", "claim_amount": 160000, "insurer_decision": "denied", "insurer_amount": 0, "insurer_reason": "Skadan har uppstått genom långvarig fuktpåverkan som undantas i villkoren.", "expected_refs": ["FAL 4 kap 11 §"]},
  {"name": "vitvaror-maskinskada", "damage_category": "Vitvaruskada", "damage_description": "Värmepumpen havererade efter åsknedslag. Bolaget gör åldersavdrag 70% på en sju år gammal pump.", "insurance_company": "If", "claim_amount": 85000, "insurer_decision": "partial", "insurer_amount": 25500, "insurer_reason": "Åldersavdrag enligt tabell för maskinell utrustning.", "expected_refs": ["FAL 6 kap 1 §"]},
  {"name": "nedsattning-sakerhetsforeskrift", "damage_category": "Underbetalt ärende", "damage_description": "Vattenskada från tvättmaskin. Bolaget sätter ned ersättningen 25% för att avstängningskran inte användes, trots att villkoret aldrig framhållits.", "insurance_company": "Länsförsäkringar", "claim_amount": 140000, "insurer_decision": "partial", "insurer_amount": 105000, "insurer_reason": "Säkerhetsföreskrift om avstängning ej följd.", "expected_refs": ["FAL 4 kap 6 §", "FAL 2 kap 8 §"]},
  {"name": "avslag-preskription", "damage_category": "Avslaget ärende", "damage_description": "Bolaget avslår anmälan om takskada med motiveringen att skadan anmäldes för sent, fyra år efter upptäckt.", "insurance_company": "Trygg-Hansa", "claim_amount": 190000, "insurer_decision": "denied", "insurer_amount": 0, "insurer_reason": "Preskription: kravet framställdes för sent.", "expected_refs": ["FAL 7 kap 4 §"]},
  {"name": "ansvar-brf", "damage_category": "Ansvar bostadsrätt/hyresrätt", "damage_description": "Vattenskada i bostadsrätt spred sig till grannlägenheten. Föreningen kräver att medlemmen betalar grannens självrisk; oklart ansvar mellan BRF och medlem.", "insurance_company": "Folksam", "claim_amount": 60000, "insurer_decision": "pending", "insurer_amount": null, "insurer_reason": "", "expected_refs": ["Bostadsrättslagen 7 kap 12 §"]},
  {"name": "badrum-tatskikt", "damage_category": "Vattenskada", "damage_description": "Läckage genom tätskikt i badrum byggt 2009. Bolaget nekar helt: badrummet uppfyllde inte branschregler vid byggtillfället.", "insurance_company": "If", "claim_amount": 250000, "insurer_decision": "denied", "insurer_amount": 0, "insurer_reason": "Bristfälligt tätskikt, ej fackmässigt utfört våtrum.", "expected_refs": ["FAL 4 kap 11 §", "FAL 4 kap 6 §"]}
]
```

- [ ] **Step 2: Runner**

`backend/evals/run_evals.py`:
```python
"""Run the draft pipeline against the golden set. Live LLM + Voyage calls.

Usage (from backend/):
    python evals/run_evals.py            # all 10 cases
    python evals/run_evals.py --limit 3  # smoke run
    python evals/run_evals.py --keep     # keep EVAL- cases in the DB
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db import SessionLocal, init_db
from app.draft_ai import create_job, run_draft_job
from app.models import Case, DraftJob, ResponseDraft
from app.verify import normalize_lagrum

GOLDEN = Path(__file__).parent / "golden_cases.json"
RESULTS_DIR = Path(__file__).parent / "results"


def expected_hit(expected_refs, draft):
    cited = {c.lower() for c in (draft.citations_used or [])}
    evidence_titles = {d["title"].lower() for d in (draft.evidence or [])}
    for ref in expected_refs:
        norm = (normalize_lagrum(ref) or ref).lower()
        if norm in cited or norm in evidence_titles:
            return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    init_db()
    cases = json.loads(GOLDEN.read_text())
    if args.limit:
        cases = cases[: args.limit]

    rows = []
    db = SessionLocal()
    try:
        for i, spec in enumerate(cases):
            case_id = f"EVAL-{datetime.utcnow().strftime('%H%M%S')}-{i}"
            db.add(Case(
                id=case_id,
                customer_name="Eval Person", customer_email="eval@example.se",
                customer_phone="", property_address="", property_type="villa",
                insurance_company=spec["insurance_company"], insurance_policy_number="",
                insurance_type="villa", damage_category=spec["damage_category"],
                damage_description=spec["damage_description"], damage_date="2026-05-01",
                claim_amount=spec.get("claim_amount"),
                insurer_decision=spec.get("insurer_decision"),
                insurer_amount=spec.get("insurer_amount"),
                insurer_reason=spec.get("insurer_reason"),
                tags=["eval"],
            ))
            db.commit()
            job = create_job(db, case_id, "maximize_payout", "")
            t0 = time.time()
            run_draft_job(job.id)
            elapsed = round(time.time() - t0, 1)
            db.expire_all()
            job = db.query(DraftJob).filter(DraftJob.id == job.id).first()
            draft = db.query(ResponseDraft).filter(ResponseDraft.id == job.draft_id).first() if job.draft_id else None
            n_cited = len(draft.citations_used or []) if draft else 0
            n_flagged = len(draft.flagged_citations or []) if draft else 0
            rows.append({
                "name": spec["name"],
                "job_status": job.status,
                "draft_status": draft.status if draft else "-",
                "cited": n_cited,
                "flagged": n_flagged,
                "validity": round(n_cited / (n_cited + n_flagged), 2) if (n_cited + n_flagged) else 0.0,
                "expected_hit": expected_hit(spec["expected_refs"], draft) if draft else False,
                "model": draft.model_used if draft else "-",
                "seconds": elapsed,
                "error": (job.error or "")[:120],
            })
            print(f"[{i + 1}/{len(cases)}] {spec['name']}: {job.status} ({elapsed}s)")
        if not args.keep:
            for c in db.query(Case).filter(Case.id.like("EVAL-%")).all():
                db.delete(c)
            db.commit()
    finally:
        db.close()

    done = [r for r in rows if r["job_status"] == "done"]
    summary = {
        "completion_rate": round(len(done) / len(rows), 2) if rows else 0,
        "avg_validity": round(sum(r["validity"] for r in done) / len(done), 2) if done else 0,
        "expected_ref_hit_rate": round(sum(r["expected_hit"] for r in done) / len(done), 2) if done else 0,
        "needs_review_rate": round(sum(r["draft_status"] == "needs_review" for r in done) / len(done), 2) if done else 0,
        "avg_seconds": round(sum(r["seconds"] for r in done) / len(done), 1) if done else 0,
    }

    RESULTS_DIR.mkdir(exist_ok=True)
    report = RESULTS_DIR / f"{datetime.utcnow().strftime('%Y-%m-%d-%H%M')}.md"
    lines = ["# Draft pipeline eval", "", f"Run: {datetime.utcnow().isoformat()} · {len(rows)} cases", "",
             "| case | job | draft | cited | flagged | validity | expected hit | model | s |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['name']} | {r['job_status']} | {r['draft_status']} | {r['cited']} | "
                     f"{r['flagged']} | {r['validity']} | {'✓' if r['expected_hit'] else '✗'} | {r['model']} | {r['seconds']} |")
    lines += ["", "## Summary", "", "```json", json.dumps(summary, indent=2), "```"]
    report.write_text("\n".join(lines))
    print(f"\nSummary: {json.dumps(summary)}")
    print(f"Report: {report}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: gitignore results** — append to `.gitignore`: `backend/evals/results/`

- [ ] **Step 4: Commit** `feat(evals): golden set + draft pipeline eval runner`

---

### Task 11: End-to-end verification (live)

- [ ] **Step 1: Full test suite** — `cd backend && python -m pytest tests/ -v` → all pass.
- [ ] **Step 2: Boot backend** — `python run.py` (background), `curl localhost:8000/api/status` → ok. Confirm ARN imported (`curl -s -X POST localhost:8000/api/arn/import`).
- [ ] **Step 3: Live ask** — `curl -s -X POST localhost:8000/api/ask -H 'Content-Type: application/json' -d '{"question": "När får försäkringsbolaget göra åldersavdrag?"}'` → answer_markdown in Swedish + sources with lagen.nu links.
- [ ] **Step 4: Live draft job** — create a water-damage case via `POST /api/cases`, `POST /api/draft`, poll `GET /api/draft-jobs/{id}` until done. Confirm: stages snapshot populated, draft cites real FAL refs, `flagged_citations` empty or draft `needs_review`, `llm_calls` rows present (`sqlite3 data/swiftclaim.db "select stage, provider, status from llm_calls order by id desc limit 10"`).
- [ ] **Step 5: Eval smoke** — `python evals/run_evals.py --limit 2` → completes, report written.
- [ ] **Step 6: OS check** — open `os/index.html` with backend running: sync case, generate draft (stage progress visible), ask a case question, Knowledge-view ask.
- [ ] **Step 7: Commit any fixes** `fix(backend): e2e verification fixes` (only if needed).

---

## Self-review notes

- Spec coverage: job model (T1/T5/T7), provider chain + logging + PII (T2), RAG upgrades (T3), verifier (T4), pipeline (T5), Q&A (T6), endpoints + intake refactor + sweep (T7), OS (T8/T9), evals (T10), live verification (T11). Streaming/auth/feedback loop intentionally out of scope per spec.
- Type consistency: `chat_json` returns `(BaseModel, meta)` everywhere; `verify_citations` takes `List[dict]` — call sites pass `c.model_dump()`; `search_with_embedding`/`embed_queries` names match between rag.py and draft_ai.py; `DraftJobOut.draft` populated manually in `_job_out` (not from_attributes).
- `Optional[DraftJobOut]` response on `/api/draft-jobs` returns JSON `null` when no job — os/api.js treats null as "no job" correctly.
