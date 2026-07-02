# Draft Generation v2 + Vault Q&A — Design

**Date:** 2026-06-12
**Status:** Approved (user delegated technical decisions)
**Goal:** Rebuild draft generation as a reliable, observable multi-stage pipeline grounded in all vault datasets, and add a Q&A capability that answers questions with verified references back to our data. Architecture is local-first but deploy-ready.

## Context

Current `/api/draft` (`backend/app/main.py`): one blocking LLM call up to 180s, brittle `"## Strategi"` string-split parsing, citations extracted from output but never verified, no logging, no fallback. The OS client (`os/api.js`) aborts every request at 15s — the draft button times out while the backend still burns tokens. The vault has grown to 6 dataset types (Lagstiftning 1,489 / ARN 36 / Praxis 15 / Villkor 16 / Förarbeten 55 / Vägledning 5) but draft retrieval uses one generic query. `rag.py` re-reads ~1,800 files + a 21 MB embeddings JSON on every query.

## Decisions

1. **Scale target:** local-first, deploy-ready. Async job model, in-memory RAG index, SQLite job state. No hosting/auth this round.
2. **Citations:** verify + repair + flag. Letters never silently contain invented law.
3. **LLM:** deepseek-chat direct (primary) → OpenRouter `moonshotai/kimi-k2.6` (fallback). Both OpenAI-compatible, same prompts.
4. **Pipeline:** multi-stage (plan → retrieve → draft → verify), every stage's input/output stored on the job.
5. **Evals:** minimal golden set (~10 cases), manual run.
6. **Q&A:** synchronous `/api/ask` endpoint, grounded in the vault, same verifier as drafts.
7. **PII guard:** customer PII replaced with placeholders before any LLM call, substituted back post-verify.

## Architecture

### New/changed modules

| File | Role |
|------|------|
| `backend/app/llm.py` | Shared LLM client: provider chain, JSON-mode helper with schema validation, retries, PII scrubbing, every call logged to `llm_calls` table. `intake_ai.py` refactored onto it. |
| `backend/app/draft_ai.py` | 4-stage draft pipeline. |
| `backend/app/qa_ai.py` | Q&A: retrieve → answer → verify references. |
| `backend/app/verify.py` | Citation verifier: lagrum normalization, resolution against vault/DB. Shared by draft + Q&A. |
| `backend/app/rag.py` | Upgrades: in-memory singleton index, `search_vault(query, dirs, k, min_score)`, whole-statute exclusion, batched multi-query embedding. |
| `backend/app/models.py` | New `DraftJob`, `LLMCall` tables; `ResponseDraft` gains columns. |
| `backend/evals/` | `golden_cases.json` + `run_evals.py`. |
| `backend/tests/` | pytest for pure functions (verifier, PII scrub, thresholds). |
| `os/api.js`, `os/app.js`, `os/index.html`, `os/styles.css` | Job polling with stage progress, flagged-citation display, ask UI. |

### Job model

- `DraftJob`: `id` (uuid), `case_id`, `status` (`queued|planning|retrieving|drafting|verifying|done|failed`), `stages` JSON (per-stage input/output snapshots), `error`, `draft_id`, `pipeline_version`, timestamps.
- Execution: FastAPI `BackgroundTasks`. Pipeline function takes `job_id` only → can move to a real worker later without API change. Job thread uses its own DB session.
- SQLite: WAL mode + `busy_timeout` (API thread and job thread write concurrently).
- Startup sweep: jobs left in a running state are marked `failed: "server restarted"`. No zombies.
- `LLMCall`: `job_id` (nullable), `stage`, `provider`, `model`, `latency_ms`, `status`, `error`, `prompt_text`, `response_text`, `created_at`. Full reconstruction of what the model saw.

### API

```
POST /api/draft {case_id, strategy?, additional_context?} → 202 {job_id}
GET  /api/draft-jobs/{job_id}   → {status, stage, draft?, error?}
GET  /api/draft-jobs?case_id=X  → latest job for case (re-attach after page reload)
POST /api/ask {question, case_id?} → {answer_markdown, sources[], unverified_refs[]}
GET  /api/draft/{case_id}       → unchanged (list drafts)
```

Old synchronous `/api/draft` behavior is replaced. `ResponseDraft` gains `flagged_citations` JSON, `evidence` JSON, `model_used`, `job_id`; `status` adds `needs_review`. Lightweight `ALTER TABLE` startup migration (same pattern as intake project).

## Draft pipeline

**Stage 1 — PLAN** (LLM, JSON mode). Case fields → `{arguments: [{claim, queries[], dataset_types[]}], missing_info[]}`, max 4 arguments, ≤6 retrieval queries total. The planner maps each argument to dataset types (`lagstiftning|arn|praxis|villkor|forarbeten|vagledning`). LLM failure → fallback plan: one argument, queries derived from case fields, all dataset types. Never kills the job.

**Stage 2 — RETRIEVE** (no LLM). All plan queries embedded in **one** Voyage batch call (rate-limit friendly). Per query: vault search filtered to mapped dirs, `k=4`, `min_score=0.35`. Dedupe by path. Budget: ≤12 docs, ≤2,500 chars each, numbered `[DOC-1]…`. Docs carry `source_url` from note frontmatter when present. Zero docs survive → pipeline continues, final draft force-marked `needs_review`.

**Stage 3 — DRAFT** (LLM, JSON mode). Case + plan + evidence → `{strategy_note, letter: {subject, body_markdown}, citations: [{ref, doc_id}], demands[], deadline_days}`. Prompt rules: every legal claim must cite a `[DOC-n]` or an exact lagrum reference; Swedish, professional-firm tone. Schema validation via pydantic; parse failure → one reprompt with the validation error, then next provider. Provider exhaustion → job `failed`.

**Stage 4 — VERIFY** (mechanical + repair). Each citation resolved against: evidence doc ids → normalized vault titles → `LawSection.full_reference` → ARN ids. Normalizer handles common lagrum forms ("FAL 4 kap 6 §", "4 kap. 6 § FAL", statute aliases from `SFS_MAP`). Unresolved → one repair LLM call (letter + invalid refs + valid evidence → corrected letter JSON), re-verify. Still invalid → draft saved `status: needs_review` with `flagged_citations`. Repair-call failure → flag-only path, never job failure.

**PII guard:** `customer_name`, `customer_email`, `customer_phone`, `property_address` replaced with `[KUND]`, `[EPOST]`, `[TELEFON]`, `[ADRESS]` in all prompt text (including occurrences inside descriptions); placeholders substituted back in the final letter/answer. Raw PII never reaches DeepSeek/OpenRouter.

## Q&A (`/api/ask`)

1. Embed question (1 Voyage call) → `search_vault` across all dataset dirs, `k=8`, `min_score=0.35`.
2. One LLM call (JSON mode): `{answer_markdown, citations: [{ref, doc_id}]}`. Case-scoped questions prepend PII-scrubbed case fields.
3. Verify citations mechanically (no repair call). Response: `sources[]` = verified refs with `title`, `path`, `score`, `source_url`; `unverified_refs[]` listed separately so the UI can mark them.
4. Synchronous endpoint; client timeout for this call raised to 90s. Calls logged to `llm_calls` (`job_id` null, stage `ask`).

## Reliability mechanics

- Provider chain per LLM call: DeepSeek direct (timeout 120s, 1 retry on 5xx/timeout) → OpenRouter kimi-k2.6 (same policy).
- Stage failure policy: PLAN degrades, RETRIEVE degrades (`needs_review`), DRAFT fails the job, VERIFY-repair degrades to flag-only.
- No silent exception swallowing anywhere in the new path; every failure lands in `DraftJob.error` or `LLMCall.error`.
- Jobs always terminate `done` or `failed` (pipeline wrapped in try/except; startup sweep covers crashes).

## RAG upgrades (`rag.py`)

- **In-memory singleton index**: notes + embeddings loaded once at first use; refreshed when the cache file mtime changes. Kills per-request reload of ~1,800 files + 21 MB JSON.
- **Whole-statute exclusion**: notes >15,000 chars dropped from retrieval (the 12 full-law files; paragraph files are small).
- `search_vault(query, dirs, k, min_score)` as the core API; `search_law` / `search_precedents` become thin wrappers so intake keeps working unchanged.
- `retrieve_many(queries)` embeds all queries in one Voyage batch call.

## OS integration

- `os/api.js`: `generateDraft()` → POST job, poll `GET /api/draft-jobs/{id}` every 3s (max 8 min) with progress callback; `getLatestDraftJob(caseId)` re-attach; `ask(question, caseId?)` with 90s timeout.
- `os/app.js` + `index.html` + `styles.css`:
  - Draft panel: Swedish stage progress ("Planerar argument…", "Söker rättskällor…", "Skriver utkast…", "Verifierar källor…"), then letter + strategy + citation list with verified badge / flagged warning, `source_url` links out to lagen.nu.
  - `needs_review` drafts visibly marked.
  - Ask box in Knowledge view (vault-wide) and in case legal panel (case-scoped); answer rendered with source list.

## Evals (`backend/evals/`)

- `golden_cases.json`: 10 realistic cases across damage categories (vattenskada/åldersavdrag, brand/aktsamhetskrav, storm, inbrott/värdering, mögel/undantag, vitvaror, nedsättning/säkerhetsföreskrift, avslag, ansvar BRF, badrum/tätskikt). Each lists `expected_refs` (any-of acceptable lagrum) and case fields.
- `run_evals.py` (live LLM, manual run): per case runs the pipeline and reports — completion rate, schema conformance, citation validity %, expected-ref hit rate, `needs_review` rate, latency. Markdown report to `backend/evals/results/`. `--limit N` for cheap smoke runs.
- pytest unit tests for deterministic parts: lagrum normalizer, citation resolution, PII scrub round-trip, threshold filtering, frontmatter `source_url` extraction.

## Out of scope

- Auth, rate limiting, hosting (deploy step)
- Streaming/SSE (polling sufficient)
- Outcome↔prediction feedback loop
- Q&A conversation history persistence
- Re-scraping/refreshing statute data
