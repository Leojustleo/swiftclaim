# AI Intake Analysis — Design

**Date:** 2026-06-11
**Status:** Approved
**Goal:** Every incoming claim query is AI-categorized and checked against the legal knowledge vault. The submitter gets an instant assessment; the full analysis is stored on the case for the OS dashboard.

## Context

Parent request: connect the future production page (dapper-clone, to be rebranded in sub-project 2) to the knowledge backend. This sub-project builds the page-agnostic backend capability; the existing static site or any client can call it.

## Endpoint

`POST /api/intake/analyze`

**Request** (`IntakeAnalyzeRequest`): `customer_name`, `customer_email`, `damage_description` (required); optional: `customer_phone`, `property_address`, `property_type`, `insurance_company`, `damage_category` (AI fills/corrects if empty), `damage_date`, `claim_amount`, `insurer_decision`, `insurer_amount`, `insurer_reason`, `tags`.

**Response** (`IntakeAnalysisOut`):
- `case_id` — server-generated `SC-yymm-nnn` (collision-checked against DB)
- `category` — one of the 10 OS damage categories
- `strength` — `stark` | `medel` | `svag` | `okänd`
- `summary` — customer-safe Swedish paragraph
- `matched_laws[]` — `{ref, title, score, excerpt}`
- `matched_precedents[]` — `{id, title, score, excerpt}`
- `key_arguments[]`, `missing_info[]` — Swedish strings
- `degraded` — true when LLM unavailable (keyword fallback used)

## Pipeline (`backend/app/intake_ai.py`)

1. **Categorize** — deepseek-chat, JSON mode: classify description into the 10 categories.
2. **Check** — existing RAG: `search_law(query, k=5)` + `search_precedents(category, text, k=5)`.
3. **Assess** — second LLM call with hits as context → strength, key arguments, missing info, summary.
4. **Persist** — create `Case` (status `intake`) with `ai_analysis` JSON column (new). Lightweight startup `ALTER TABLE` for existing SQLite DBs.
5. **Degradation** — LLM failure → keyword categorizer (port of OS `inferCategory`), RAG hits still returned, `strength: "okänd"`, never a 5xx for LLM issues.

## OS integration

`CaseOut` exposes `ai_analysis`. OS `syncFromBackend()` attaches a note (author "AI-analys") with summary, strength, arguments, and matched refs — renders in the existing notes UI.

## Out of scope

Clone rebrand, intake/assessment UI, moving clone into `web/` (sub-project 2). Streaming/async job queue (synchronous is fine at MVP latency ~10-30s).
