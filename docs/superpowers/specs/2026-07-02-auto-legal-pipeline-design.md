# Automated Legal Pipeline — Design

**Date:** 2026-07-02
**Status:** Approved by Leo (full-auto-to-review-queue, unified scorecard, ARN corpus expansion, trigger on any case creation, flexible ingestion of new data at any time)

## Goal

Every new SwiftClaim case — from the website intake form or the admin dashboard — automatically runs the full legal workflow with no human clicks: research → scorecard → appeal draft → review queue. A human (legally-savvy team member) only reviews and approves the final letter. The knowledge base accepts new data sources (court decisions, statutes, guidelines, any datapoint) at any time and they become retrievable without code changes.

## Non-goals (deliberately out of scope)

- Auto-sending anything to insurers or ARN — human sign-off stays mandatory.
- New customer-facing frontend surfaces; only the admin dashboard grows a review queue.
- Multi-worker/queue infrastructure (Celery, Redis). In-process background jobs with the existing stale-job guard are sufficient at current volume.
- Agentic LLM orchestration — deterministic staged pipeline only, because verifiability is the product.

## Architecture

In-process extension of the existing FastAPI backend (Approach A). One new orchestrator chains the existing, already-hardened pieces. All LLM traffic goes through `app/llm.py` (`chat_json`: PII scrub, provider fallback, `llm_calls` logging).

```
case created (intake form or dashboard)
        │
        ▼
PipelineJob row + BackgroundTask ──── stages: research → scorecard → draft → done
        │                                          (fail_if_stale guard reused)
        ├─ research:  hybrid RAG over vault (laws + ARN + praxis + any new dirs)
        ├─ scorecard: unified scorecard (scorecard.py) — one structured chat_json call
        │             + citation resolution via verify.py; unresolved refs flagged
        ├─ draft:     existing draft-generation v2 (create_job/run_draft_job) as-is
        ▼
case.status = "needs_review" → admin review queue (sorted by priority/score)
        │
        ▼
human approves / edits / rejects → outcome recorded when case resolves
```

## Components

### 1. Unified scorecard — `backend/app/scorecard.py` (replaces `scoring.py`)

Single source of truth for case merit. `scoring.py` (direct DeepSeek call, no PII scrub, no fallback, no logging) is deleted; callers migrate.

- Input: case field dict (same shape both `intake_ai` and admin use today).
- Flow: PII-scrub → RAG retrieval (`search_law` + `search_precedents`, plus any new vault dirs) → one `chat_json` call with a Pydantic output schema → derive fields → resolve citations.
- Output schema:
  - `claim_strength: int 0–100`
  - `strength_band: "stark" | "medel" | "svag"` — derived: ≥70 stark, ≥40 medel, else svag
  - `win_probability: str` (e.g. `"68%"`)
  - `priority: "high" | "medium" | "low"` — derived from `claim_strength` (same thresholds as band)
  - `key_factors: list[str]`
  - `recommended_action: str`
  - `arn_references: list[str]`, `lagrum_references: list[str]`
  - `flagged_references: list[str]` — citations that did not resolve against the vault (verify.py normalizer); shown as unverified, never as fact
  - `degraded: bool` — LLM/RAG failure fell back to partial output
- `intake_ai.assess` is replaced by a thin wrapper deriving `strength_band` from the unified score — one brain, two views.
- Stored on `Case.scorecard` (JSON column, exists today) — admin dashboard keeps working with richer data.

### 2. Pipeline orchestrator — `backend/app/pipeline.py`

- New `PipelineJob` model (mirrors `DraftJob`): `id`, `case_id`, `status` (`research`/`scoring`/`drafting`/`done`/`failed`), `error`, stage snapshots, timestamps.
- Trigger: case creation from any source — the intake endpoint and the case-create endpoint both enqueue via `BackgroundTasks`.
- Stages call existing code: research = RAG retrieval; scorecard = component 1; draft = existing `draft_ai.create_job`/`run_draft_job` awaited in-process.
- Failure isolation per stage: scorecard failure → case still reaches the queue marked scoring-degraded; draft failure → queue with scorecard only. A stage failure never blocks the case from reaching a human.
- `fail_if_stale` guard applied to `PipelineJob` exactly as for `DraftJob`.
- Terminal effect: `case.status = "needs_review"`.
- Endpoints: `GET /api/pipeline-jobs/{id}`, `GET /api/pipeline-jobs?case_id=`.

### 3. Flexible knowledge ingestion (new data at any time)

The vault is the ingestion contract: **any `.md` file with YAML frontmatter dropped into any top-level vault directory becomes retrievable after reindex — no code change.**

- `rag.py`: replace the hardcoded `DIR_MAP` with auto-discovery of top-level vault directories (skip dot-dirs and `Index/`); keep the existing keys as stable aliases so current callers (`dirs=["arn"]` etc.) don't break. New dirs (e.g. `Domar/` for court decisions, `Övrigt/`) are searchable immediately.
- `POST /api/reindex` (admin): triggers the existing hash-based incremental embed (`build_or_load_index`) in a background task; only new/changed files hit the Voyage API. Response reports files added/updated. `GET /api/reindex/status` for progress.
- Frontmatter convention for new sources documented in the vault README: minimum `title` + `type`; retrieval works without richer metadata.

### 4. Review queue — admin dashboard extension

- List view filtered `status = needs_review`, sorted by priority then `claim_strength` desc.
- Case detail shows: full scorecard (including `flagged_references` clearly marked unverified), the draft with its citation-verification status, and pipeline stage history.
- Actions: approve draft / edit-then-approve / reject (case returns to manual handling). Approval sets `case.status = "approved"`; nothing is sent anywhere automatically.

### 5. Outcome tracking (calibration)

- New `Case` columns: `actual_outcome` (`won`/`partial`/`lost`/`withdrawn`/null), `actual_amount_sek` (nullable int), `outcome_date` (nullable date). Settable from the admin case view.
- Stats endpoint extension: predicted win probability vs. actual win rate, bucketed (e.g. predicted 60–80% → actual N/M won), so the scorecard proves itself on real cases over time.

### 6. ARN corpus expansion (batch job, not new code)

- Run the existing law-pipeline (scrape → extract → LLM-anonymize → vault) at scale, targeting a few hundred property/insurance ARN decisions (from today's 36).
- Then: incremental reindex + wiki index + `summary.json` rebuild.
- Small pipeline tweaks only as needed to run at volume (rate limits, resume on failure).

## Error handling

- Every LLM call: `chat_json` chain (retry, provider fallback, malformed/truncation guards — already hardened 2026-07-02).
- Every pipeline stage: catch, record on the job row, degrade, continue to the queue. No case silently disappears.
- Reindex: per-file failures logged and skipped; a bad file never blocks the batch.

## Testing & evals

- **Pytest (no live calls, matches existing suite):** band/priority derivation, scorecard output parsing with fake `chat_json`, orchestrator state transitions and failure isolation with fakes, DIR auto-discovery, outcome-field validation.
- **Evals (`backend/evals`, live keys):** scorecard golden set of 10–15 cases labeled by the legal team members (expected strength band + must-cite references). Thresholds: 100% citation resolution on non-flagged refs; band-match rate reported per run.
- **Calibration:** not a launch gate — accumulates on real cases via component 5.

## Success criteria

1. Creating a case via intake form or dashboard produces, with zero clicks: a stored unified scorecard, a citation-verified draft (or a degraded-but-queued case), and `needs_review` status.
2. Dropping a new `.md` source into a brand-new vault directory + calling `/api/reindex` makes it retrievable in RAG search and eligible for scorecards.
3. All existing tests pass; new unit tests cover the orchestrator and scorecard logic; eval run meets thresholds on the golden set.
4. `scoring.py`'s unguarded direct-DeepSeek path no longer exists.
