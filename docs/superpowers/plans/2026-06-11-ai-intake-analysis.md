# AI Intake Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `POST /api/intake/analyze` — AI categorizes incoming queries, checks them against the legal vault, stores + returns the assessment.

**Architecture:** New `intake_ai.py` module (categorize → RAG check → assess → persist), one new route in `main.py`, `ai_analysis` JSON column on `Case` with startup ALTER migration, OS sync attaches analysis as a case note.

**Tech Stack:** FastAPI, SQLAlchemy/SQLite, httpx → DeepSeek (JSON mode), existing Voyage RAG.

**Spec:** `docs/superpowers/specs/2026-06-11-ai-intake-analysis-design.md`

Manual verification per task (no test suite — consistent with MVP spec).

---

### Task 1: `ai_analysis` column + migration

**Files:** Modify `backend/app/models.py`, `backend/app/db.py`, `backend/app/schemas.py`

- [ ] Add to `Case` model: `ai_analysis = Column(JSON, nullable=True)`
- [ ] In `db.py` `init_db()`, after `create_all`, run idempotent migration: query `PRAGMA table_info(cases)`, if `ai_analysis` missing → `ALTER TABLE cases ADD COLUMN ai_analysis JSON`
- [ ] Add `ai_analysis: Optional[dict] = None` to `CaseOut`
- [ ] Verify: restart backend, `curl -s localhost:8000/api/cases | python3 -m json.tool | grep ai_analysis`

### Task 2: `backend/app/intake_ai.py`

**Files:** Create `backend/app/intake_ai.py`

- [ ] `CATEGORIES` list (10 OS categories), `_llm_json(system, user)` helper (DeepSeek JSON mode, 60s timeout, raises on failure)
- [ ] `keyword_category(text)` — port of OS `inferCategory` keyword rules
- [ ] `categorize(description)` → `{category}` via LLM, fallback `keyword_category`
- [ ] `assess(case_fields, law_hits, arn_hits)` → `{strength, summary, key_arguments, missing_info}` via LLM; fallback degraded dict
- [ ] `analyze(payload, db)` orchestrator: categorize → `search_law` + `search_precedents` → assess → create Case with server-generated id (`SC-yymm-nnn`, collision-checked) → store `ai_analysis` → return response dict
- [ ] Verify: `python3 -c "import sys; sys.path.insert(0,'backend'); from app import intake_ai"` clean import

### Task 3: Route + schemas

**Files:** Modify `backend/app/main.py`, `backend/app/schemas.py`

- [ ] `IntakeAnalyzeRequest` + `IntakeAnalysisOut` schemas per spec
- [ ] `POST /api/intake/analyze` → `intake_ai.analyze(...)`
- [ ] Verify: curl realistic vattenskada query → JSON with category `Vattenskada`, FAL refs in `matched_laws`, vault ids in `matched_precedents`, case row created with `ai_analysis`

### Task 4: OS shows analysis

**Files:** Modify `os/app.js` (`syncFromBackend`)

- [ ] After `createCaseFromPayload`, if `remote.ai_analysis` → unshift note `{author: "AI-analys", body: <formatted summary/strength/arguments/refs>}` onto `newCase.notes`
- [ ] Verify: clear OS storage, reload, open synced case → AI-analys note visible

### Task 5: Verify end-to-end, commit, push

- [ ] Degradation check: temporarily unset key → endpoint returns `degraded: true`, no 5xx (restore after)
- [ ] Commits: `feat(backend): AI intake analysis — categorize, vault check, assessment`, `feat(os): show AI analysis on synced cases`, docs commit
- [ ] `git push origin main`
