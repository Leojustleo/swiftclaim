# AI Engine Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix six correctness/robustness defects found in a review of the AI engine (`backend/app/llm.py`, `intake_ai.py`, `draft_ai.py`, `qa_ai.py`, `main.py`): malformed-response crashes, silent output truncation, PII gaps (policy number + entire intake path), case-id exhaustion, and draft jobs stuck forever after a server restart.

**Architecture:** All changes are small, local edits to the existing FastAPI backend. No new modules except one new test file. The LLM provider chain in `llm.py` gains two new failure classifications (malformed body, truncated output) that flow through the existing retry/fallback loop. The intake path gains the same PII scrubbing the draft path already has. TDD throughout: every task starts with a failing test.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy, pytest (existing suite: `cd backend && python3 -m pytest tests/` — 36 tests passing before this plan).

**Working directory for all commands:** `/Users/leo-mac/claude-code/Swiftclaim/backend`

---

### Task 1: llm.py — malformed 200 response must not crash the pipeline

`chat_json` does `r.json()["choices"][0]["message"]["content"]` unguarded (`app/llm.py:148`). A 200 response with an error-shaped body, missing `choices`, or `content: null` raises `KeyError`/`TypeError`/JSON decode errors that escape `chat_json` as a generic exception — the draft job fails with `TypeError: ...` instead of falling through to the next attempt/provider.

**Files:**
- Modify: `backend/app/llm.py:148`
- Test: `backend/tests/test_llm_chain.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_llm_chain.py`:

```python
class ErrorBodyResponse(FakeResponse):
    def json(self):
        return {"error": {"message": "overloaded"}}


class NullContentResponse(FakeResponse):
    def json(self):
        return {"choices": [{"message": {"content": None}}]}


def test_malformed_200_falls_through_to_next_provider(monkeypatch):
    def fake_post(url, **kwargs):
        if "deepseek" in url:
            return ErrorBodyResponse(200, text="overloaded")
        return FakeResponse(200, content=json.dumps({"x": 3}))

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    monkeypatch.setattr(llm, "PROVIDERS", [
        {"name": "deepseek", "url": "https://api.deepseek.com/x", "model": "m1", "key": lambda: "k"},
        {"name": "openrouter", "url": "https://openrouter.ai/x", "model": "m2", "key": lambda: "k"},
    ])
    parsed, meta = llm.chat_json("s", "u", Out)
    assert parsed.x == 3
    assert meta["provider"] == "openrouter"


def test_null_content_raises_llm_error_not_type_error(monkeypatch):
    monkeypatch.setattr(llm.httpx, "post", lambda url, **kw: NullContentResponse(200))
    monkeypatch.setattr(llm, "PROVIDERS", [
        {"name": "deepseek", "url": "u", "model": "m", "key": lambda: "k"},
    ])
    with pytest.raises(llm.LLMError):
        llm.chat_json("s", "u", Out)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_llm_chain.py -v`
Expected: the two new tests FAIL (`KeyError: 'choices'` / `TypeError` escaping instead of provider fallback / `LLMError`). The three existing tests still pass.

- [ ] **Step 3: Implement the guard**

In `backend/app/llm.py`, replace this line (line 148):

```python
            raw = r.json()["choices"][0]["message"]["content"]
```

with:

```python
            try:
                choice = r.json()["choices"][0]
                raw = choice["message"]["content"]
            except (KeyError, IndexError, TypeError, ValueError):
                raw = None
            if not isinstance(raw, str) or not raw.strip():
                last_err = f"{prov['name']}: malformed response body"
                _log_call(db, job_id, stage, prov["name"], prov["model"], "error",
                          f"malformed: {r.text[:300]}", latency, prompt_log, None)
                continue
```

(`choice` is also used by Task 2 — keep the variable name.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_llm_chain.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_llm_chain.py app/llm.py
git commit -m "fix: chat_json survives malformed 200 responses via provider fallback"
```

---

### Task 2: llm.py — detect truncated output instead of re-prompting it

When output hits `max_tokens`, the JSON is cut mid-string. Today that surfaces as a `ValidationError`, which triggers the schema re-prompt with the *same* `max_tokens` — guaranteed to fail again and burn both attempts. The API reports this explicitly via `finish_reason: "length"`. Also bump the draft-writing stage from the 4000-token default to 6000 (a full Swedish letter + JSON envelope can exceed 4000).

**Files:**
- Modify: `backend/app/llm.py` (inside `chat_json`, right after the Task 1 guard)
- Modify: `backend/app/draft_ai.py:247-248`
- Test: `backend/tests/test_llm_chain.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_llm_chain.py`. First extend `FakeResponse` (edit the existing class — add the `finish_reason` parameter):

```python
class FakeResponse:
    def __init__(self, status_code, content=None, text="", finish_reason="stop"):
        self.status_code = status_code
        self.text = text
        self._content = content
        self._finish_reason = finish_reason

    def json(self):
        return {"choices": [{"message": {"content": self._content},
                             "finish_reason": self._finish_reason}]}
```

Then add the test:

```python
def test_truncated_output_skips_schema_reprompt(monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append(kwargs["json"]["messages"])
        if "deepseek" in url:
            return FakeResponse(200, content='{"x": ', finish_reason="length")
        return FakeResponse(200, content=json.dumps({"x": 5}))

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    monkeypatch.setattr(llm, "PROVIDERS", [
        {"name": "deepseek", "url": "https://api.deepseek.com/x", "model": "m1", "key": lambda: "k"},
        {"name": "openrouter", "url": "https://openrouter.ai/x", "model": "m2", "key": lambda: "k"},
    ])
    parsed, meta = llm.chat_json("s", "u", Out)
    assert parsed.x == 5
    # no re-prompt: every request must be the original 2-message payload
    assert all(len(m) == 2 for m in calls)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_llm_chain.py -v`
Expected: `test_truncated_output_skips_schema_reprompt` FAILS — the truncated body goes down the `ValidationError` path and appends a 4-message re-prompt, so `all(len(m) == 2 ...)` is false. All other tests pass (the `FakeResponse` change is backward-compatible: default `finish_reason="stop"`).

- [ ] **Step 3: Implement truncation detection**

In `backend/app/llm.py`, directly after the malformed-body guard from Task 1 (i.e. after the `continue` of that block, before `try: parsed = schema.model_validate_json(raw)`), insert:

```python
            if choice.get("finish_reason") == "length":
                last_err = f"{prov['name']}: output truncated at max_tokens={max_tokens}"
                _log_call(db, job_id, stage, prov["name"], prov["model"], "error",
                          last_err, latency, prompt_log, raw)
                continue
```

In `backend/app/draft_ai.py`, change the draft-stage call (lines 247-248):

```python
    out, meta = chat_json(DRAFT_SYSTEM, user_msg, DraftOutput,
                          db=db, job_id=job.id, stage="draft.write", max_tokens=6000)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/ -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_llm_chain.py app/llm.py app/draft_ai.py
git commit -m "fix: treat finish_reason=length as provider error, bump draft max_tokens"
```

---

### Task 3: PII — scrub insurance policy number

`case_block` (`app/draft_ai.py:122`) sends `insurance_policy_number` verbatim to DeepSeek/OpenRouter, but `PII_FIELDS` (`app/llm.py:16`) doesn't include it. It uniquely identifies the customer at the insurer — same sensitivity class as name/address. The existing scrub/unscrub round-trip means the final letter still gets the real number back after generation.

**Files:**
- Modify: `backend/app/llm.py:16-21`
- Test: `backend/tests/test_pii.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_pii.py` (extend the module-level `FIELDS` dict with the new key, and add the test):

```python
FIELDS = {
    "customer_name": "Anna Andersson",
    "customer_email": "anna@example.se",
    "customer_phone": "0701234567",
    "property_address": "Storgatan 1, Lund",
    "insurance_policy_number": "HF-99887766",
}


def test_scrub_replaces_policy_number():
    text = "Försäkringsnummer: HF-99887766 hos Folksam."
    out = scrub_pii(text, FIELDS)
    assert "HF-99887766" not in out
    assert "[FÖRSNR]" in out
    assert unscrub_pii(out, FIELDS) == text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_pii.py -v`
Expected: `test_scrub_replaces_policy_number` FAILS (`"[FÖRSNR]" in out` is false). Existing tests pass.

- [ ] **Step 3: Implement**

In `backend/app/llm.py`, extend `PII_FIELDS`:

```python
PII_FIELDS = [
    ("customer_name", "[KUND]"),
    ("customer_email", "[EPOST]"),
    ("customer_phone", "[TELEFON]"),
    ("property_address", "[ADRESS]"),
    ("insurance_policy_number", "[FÖRSNR]"),
]
```

No other change needed: `case_fields()` in `draft_ai.py` already includes the key, and `scrub_pii`/`unscrub_pii` iterate `PII_FIELDS`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/ -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_pii.py app/llm.py
git commit -m "fix: scrub insurance policy number before LLM calls"
```

---

### Task 4: intake_ai — scrub PII before LLM calls, log the calls

The intake path violates the project's PII guard (CLAUDE.md: "customer name/email/phone/address replaced ... before any LLM call"): `categorize()` and `assess()` send the raw damage description and insurer reason — which routinely contain the customer's name/address — straight to the LLM, and `analyze()` sends the raw description to Voyage as the RAG query. Intake calls also pass no `db`, so nothing lands in the `llm_calls` audit table.

**Files:**
- Modify: `backend/app/intake_ai.py`
- Create: `backend/tests/test_intake_ai.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_intake_ai.py`:

```python
from app import intake_ai

FIELDS = {
    "customer_name": "Anna Andersson",
    "customer_email": "anna@example.se",
    "customer_phone": "0701234567",
    "property_address": "Storgatan 1, Lund",
    "insurance_policy_number": "HF-99887766",
}


def test_categorize_scrubs_pii(monkeypatch):
    captured = {}

    def fake_chat(system, user, schema, **kw):
        captured["user"] = user
        return schema(category="Vattenskada"), {"model": "m"}

    monkeypatch.setattr(intake_ai, "chat_json", fake_chat)
    out = intake_ai.categorize(
        "Anna Andersson fick vattenskada på Storgatan 1, Lund", fields=FIELDS)
    assert "Anna" not in captured["user"]
    assert "Storgatan" not in captured["user"]
    assert "[KUND]" in captured["user"] and "[ADRESS]" in captured["user"]
    assert out == {"category": "Vattenskada", "degraded": False}


def test_assess_scrubs_pii(monkeypatch):
    captured = {}

    def fake_chat(system, user, schema, **kw):
        captured["user"] = user
        return schema(strength="stark", summary="ok"), {"model": "m"}

    monkeypatch.setattr(intake_ai, "chat_json", fake_chat)
    fields = dict(
        FIELDS,
        damage_category="Vattenskada",
        damage_description="Läcka hos Anna Andersson, Storgatan 1, Lund",
        insurer_reason="Anna Andersson anmälde för sent",
    )
    out = intake_ai.assess(fields, law_hits=[], arn_hits=[])
    assert "Anna" not in captured["user"]
    assert "[KUND]" in captured["user"]
    assert out["strength"] == "stark"
    assert out["degraded"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_intake_ai.py -v`
Expected: FAIL — `test_categorize_scrubs_pii` with `TypeError: categorize() got an unexpected keyword argument 'fields'`; `test_assess_scrubs_pii` with `"Anna" not in captured["user"]` assertion failure.

- [ ] **Step 3: Implement**

In `backend/app/intake_ai.py`:

Change the imports block:

```python
import random
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.llm import LLMError, chat_json, scrub_pii
from app.models import Case
from app.rag import search_law, search_precedents
```

(`uuid` is used by Task 5 — if executing this task standalone, adding it now is still harmless.)

Replace `categorize`:

```python
def categorize(description: str, hint: str = "",
               fields: Optional[Dict[str, Any]] = None, db: Session = None) -> Dict[str, Any]:
    safe = scrub_pii(description, fields or {})
    user = f"Skadebeskrivning:\n{safe[:2000]}"
    if hint:
        user += f"\n\nKundens egen kategorisering: {hint}"
    try:
        out, _ = chat_json(CATEGORIZE_SYSTEM, user, CategorizeOut,
                           db=db, stage="intake.categorize", max_tokens=100)
        if out.category in CATEGORIES:
            return {"category": out.category, "degraded": False}
    except LLMError:
        pass
    return {"category": hint if hint in CATEGORIES else keyword_category(description), "degraded": True}
```

In `assess`, change the signature and the `chat_json` call:

```python
def assess(fields: Dict[str, Any], law_hits: List[Dict], arn_hits: List[Dict],
           db: Session = None) -> Dict[str, Any]:
```

and replace

```python
        out, _ = chat_json(ASSESS_SYSTEM, "\n\n".join(parts), AssessOut, stage="intake.assess", max_tokens=1200)
```

with

```python
        out, _ = chat_json(ASSESS_SYSTEM, scrub_pii("\n\n".join(parts), fields), AssessOut,
                           db=db, stage="intake.assess", max_tokens=1200)
```

In `analyze`, scrub the RAG query and thread `db` through (replace the corresponding lines):

```python
    description = payload.get("damage_description", "")
    safe_description = scrub_pii(description, payload)
    cat = categorize(description, hint=payload.get("damage_category") or "",
                     fields=payload, db=db)
    category = cat["category"]

    rag_query = f"{category} {safe_description[:300]}"
    if payload.get("insurer_reason"):
        rag_query += f" {scrub_pii(payload['insurer_reason'], payload)[:200]}"
```

and

```python
    assessment = assess(fields, law_hits, arn_hits, db=db) if not rag_failed else {
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/ -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_intake_ai.py app/intake_ai.py
git commit -m "fix: scrub PII in intake LLM/RAG calls and log them to llm_calls"
```

---

### Task 5: intake_ai — bound the case-id retry loop

`_new_case_id` (`app/intake_ai.py:126`) draws from `SC-{yymm}-{100..999}` in a `while True`. At 900 cases in a month, it never terminates and the intake request hangs forever. Bound the loop and fall back to a hex suffix.

**Files:**
- Modify: `backend/app/intake_ai.py:126-131`
- Test: `backend/tests/test_intake_ai.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_intake_ai.py` (add `import re` at the top of the file):

```python
class AlwaysTakenDB:
    def query(self, *a):
        return self

    def filter(self, *a):
        return self

    def first(self):
        return object()


def test_new_case_id_falls_back_when_pool_exhausted():
    cid = intake_ai._new_case_id(AlwaysTakenDB())
    assert re.fullmatch(r"SC-\d{4}-[0-9a-f]{6}", cid)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_intake_ai.py::test_new_case_id_falls_back_when_pool_exhausted -v`
Expected: the test HANGS (infinite loop). Kill it (Ctrl-C / timeout) — that *is* the failure demonstration. Use `timeout 10 python3 -m pytest ...` to bound it.

- [ ] **Step 3: Implement**

Replace `_new_case_id` in `backend/app/intake_ai.py`:

```python
def _new_case_id(db: Session) -> str:
    yymm = datetime.utcnow().strftime("%y%m")
    for _ in range(40):
        candidate = f"SC-{yymm}-{random.randint(100, 999)}"
        if not db.query(Case).filter(Case.id == candidate).first():
            return candidate
    return f"SC-{yymm}-{uuid.uuid4().hex[:6]}"
```

(`import uuid` was added in Task 4 Step 3.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/ -v`
Expected: all tests PASS, no hang.

- [ ] **Step 5: Commit**

```bash
git add tests/test_intake_ai.py app/intake_ai.py
git commit -m "fix: bound case-id generation, hex fallback when monthly pool exhausted"
```

---

### Task 6: draft jobs — fail stale jobs instead of polling forever

`run_draft_job` runs via FastAPI `BackgroundTasks` in-process (`app/main.py:456`). If the server restarts mid-job, the `DraftJob` row stays at `planning`/`retrieving`/... forever and the OS dashboard polls `GET /api/draft-jobs/{id}` indefinitely. Fix: when a job is fetched and hasn't been updated in 15 minutes while non-terminal, mark it failed.

**Files:**
- Modify: `backend/app/draft_ai.py` (add `fail_if_stale`)
- Modify: `backend/app/main.py:460-479` (call it from both GET endpoints)
- Test: `backend/tests/test_draft_helpers.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_draft_helpers.py` (add imports at the top if missing: `from datetime import datetime, timedelta`, `from types import SimpleNamespace`, and `fail_if_stale` from `app.draft_ai`):

```python
class FakeDB:
    def __init__(self):
        self.committed = False

    def commit(self):
        self.committed = True


def _job(status, minutes_ago):
    return SimpleNamespace(
        status=status, error=None,
        updated_at=datetime.utcnow() - timedelta(minutes=minutes_ago),
        created_at=datetime.utcnow() - timedelta(minutes=minutes_ago),
    )


def test_stale_running_job_marked_failed():
    db, job = FakeDB(), _job("planning", 30)
    fail_if_stale(db, job)
    assert job.status == "failed"
    assert "stalled" in job.error
    assert db.committed


def test_fresh_and_terminal_jobs_untouched():
    db = FakeDB()
    fresh = _job("drafting", 2)
    fail_if_stale(db, fresh)
    assert fresh.status == "drafting"
    done = _job("done", 60)
    fail_if_stale(db, done)
    assert done.status == "done"
    assert not db.committed
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_draft_helpers.py -v`
Expected: FAIL with `ImportError: cannot import name 'fail_if_stale'`.

- [ ] **Step 3: Implement**

In `backend/app/draft_ai.py`, add below the constants at the top (after `MAX_QUERIES = 6`):

```python
STALE_JOB_MINUTES = 15
```

and add this function (near `run_draft_job`):

```python
def fail_if_stale(db: Session, job: DraftJob) -> DraftJob:
    if job.status in ("done", "failed"):
        return job
    ts = job.updated_at or job.created_at
    if ts and datetime.utcnow() - ts > timedelta(minutes=STALE_JOB_MINUTES):
        job.status, job.error = "failed", "job stalled — server likely restarted mid-run"
        db.commit()
    return job
```

Update the datetime import in `draft_ai.py`:

```python
from datetime import datetime, timedelta
```

In `backend/app/main.py`, extend the import on line 25:

```python
from app.draft_ai import create_job, run_draft_job, fail_if_stale
```

and call it in both GET endpoints:

```python
@app.get("/api/draft-jobs/{job_id}", response_model=DraftJobOut)
def get_draft_job(job_id: str, db: Session = Depends(get_db)):
    job = db.query(DraftJob).filter(DraftJob.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    return _job_out(db, fail_if_stale(db, job))


@app.get("/api/draft-jobs", response_model=Optional[DraftJobOut])
def get_latest_draft_job(case_id: str, db: Session = Depends(get_db)):
    job = db.query(DraftJob).filter(DraftJob.case_id == case_id) \
        .order_by(DraftJob.created_at.desc()).first()
    return _job_out(db, fail_if_stale(db, job)) if job else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/ -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_draft_helpers.py app/draft_ai.py app/main.py
git commit -m "fix: mark draft jobs stalled >15min as failed on fetch"
```

---

## Final verification

- [ ] Run the full suite: `python3 -m pytest tests/ -v` — expect 36 pre-existing + 9 new = 45 passing.
- [ ] Smoke the evals (needs API keys in `.env`): `python3 evals/run_evals.py` — completion and citation-validity should stay at 100%.

## Deliberately out of scope (reviewed, skipped — YAGNI for now)

- **Pure-Python cosine scan** (`rag.py:_cosine`) over ~2,800 notes × 1024 dims per query (~1-2 s; draft pipeline does up to 6). numpy would cut it ~100×. Do when latency actually hurts.
- **Free-text PII** inside descriptions that isn't in a known field (e.g. a neighbour's name) is not caught by field-replace scrubbing. Would need NER/LLM-based scrubbing like the law-pipeline processor.
- **Voyage re-embed on first request after vault change**: `get_index()` triggers `build_or_load_index` inline with 22 s sleeps between batches — first API request after adding vault notes can block for minutes. Pre-warm via `seed.py`/reindex instead if it bites.
- **Praxis refs (NJA) without doc_id** get flagged by the citation verifier unless the title matches the vault exactly; refs carrying a `doc_id` already pass via the evidence check, so impact is low.
