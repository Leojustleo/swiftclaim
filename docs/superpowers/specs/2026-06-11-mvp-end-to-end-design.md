# Swiftclaim MVP — End-to-End Claim Loop on Real Data

**Date:** 2026-06-11
**Status:** Approved
**Goal:** A customer can submit a real claim on the public site, the case appears in the internal OS dashboard, and Swiftclaim generates a legally grounded draft letter using real Swedish statutes and real (anonymized) ARN precedents. The complete project is published to GitHub.

## Context

Current state before this work:

- `site/` — 8 static Swedish marketing pages. All CTAs dead-end at a `#anmal` anchor with no form anywhere.
- `os/` — internal dashboard (vanilla JS, localStorage state). Seeds **fake demo cases** via `seedCases()` when storage is empty. `os/api.js` bridge to backend exists (outbound sync, RAG search, draft generation).
- `backend/` — FastAPI + SQLite. Cases CRUD, ARN import from vault, law sections, RAG search (Voyage embeddings), LLM draft generation. **Bug:** `main.py` posts to `api.deepseek.com` using `OPENROUTER_API_KEY` — endpoint/key mismatch, drafts likely fail.
- `swiftclaim-obsidian/` — real data: 1,289 statute paragraph files (12 SFS laws), 10 anonymized ARN decisions, 7 concept notes. **Gitignored.**
- `law-pipeline/` — ARN scraper + processor + law scraper. Embeddings cache at `law-pipeline/.embeddings.json` (18 MB). **Gitignored.**
- GitHub remote `Leojustleo/swiftclaim` (public) exists and is synced at commit `83c6594` — backend, `os/api.js`, 5 site pages, vault, and pipeline are all unpushed/ignored.

## Decisions Made

1. **MVP scope:** End-to-end claim loop (not data-scaling, not deployment).
2. **Repo contents:** Everything except secrets and regenerable/PII artifacts goes to GitHub.
3. **Approach:** Local-first, backend-direct. The intake form posts to `localhost:8000`; this is an honest local MVP demoable on the founder's machine. Deployment is a later, separate step.

## Design

### 1. Flow (stack unchanged)

```
site/landing_v2.html (form)
  → POST http://localhost:8000/api/cases
  → SQLite (backend/data/swiftclaim.db)
  → OS dashboard pulls on init + manual sync button
  → RAG search over vault (1,289 laws + 10 ARN)
  → LLM draft letter (OpenRouter → deepseek-chat)
```

No new frameworks, no hosting, no auth.

### 2. Intake form (`site/landing_v2.html`)

Replace the `#anmal` CTA dead-end with a real form section, styled per `site/DESIGN_GUIDELINES.md` (navy dark section, yellow submit button, CSS variables only).

Fields (★ = required, maps to backend `CaseCreate`):

| Field | Input | Maps to |
|-------|-------|---------|
| Namn ★ | text | `customer_name` |
| E-post ★ | email | `customer_email` |
| Telefon | tel | `customer_phone` |
| Försäkringsbolag ★ | select (known companies + "Annat") | `insurance_company` |
| Typ av skada ★ | select (OS damage categories) | `damage_category` |
| Skadebeskrivning ★ | textarea | `damage_description` |
| Skadedatum | date | `damage_date` |
| Yrkat belopp (kr) | number | `claim_amount` |
| Har du redan fått beslut? | toggle group, optional | — |
| └ Bolagets beslut | select/text | `insurer_decision` |
| └ Erbjudet belopp (kr) | number | `insurer_amount` |
| └ Bolagets motivering | textarea | `insurer_reason` |

Behavior (inline vanilla JS):

- Client generates case id in the OS-compatible `SC-…` format.
- POST JSON to `http://localhost:8000/api/cases`.
- Success → replace form with a Swedish thank-you message.
- Backend unreachable → inline error message with a `mailto:` fallback link.
- No spam protection (local MVP).

### 3. OS dashboard (`os/app.js`, `os/index.html`)

- **Remove the `seedCases()` call** from `init()` — empty storage shows the real empty state, never fake data. JSON export/import remains as the backup path.
- **Inbound sync (new):** on init, and via a "Synka från backend" toolbar button, fetch `GET /api/cases`, convert with existing `backendCaseToOs()`, and merge into local state. Merge rule: **add new ids only; never overwrite locally edited cases.** New cases land with status "Ny lead".

### 4. Backend fixes (`backend/app/main.py`)

- Fix LLM endpoint: `OR_URL` → `https://openrouter.ai/api/v1/chat/completions`, model → `deepseek/deepseek-chat`. Verify with a live call.
- Seed real data: run the ARN vault import (10 decisions) and confirm law sections are seeded and the Voyage embeddings cache is warm.

### 5. Verification (no test suite in scope)

Run one realistic case (water damage) through the complete loop:

1. Backend up (`python backend/run.py`), ARN imported.
2. Submit via the site form → expect 201.
3. Case visible in OS dashboard after sync.
4. RAG search returns relevant statute hits.
5. Generate draft → letter cites real FAL paragraphs and real ARN case ids.

Verification by curl + browser (Playwright MCP if needed). No automated test suite in this MVP.

### 6. GitHub publication (public repo — handle with care)

- **`.gitignore` rewrite:** un-ignore `law-pipeline/` and `swiftclaim-obsidian/` (contents are public statutes + LLM-anonymized ARN decisions — safe to publish). Keep ignored:
  - `.env` (all locations)
  - `backend/data/*.db`
  - `law-pipeline/.embeddings.json` (18 MB, regenerable)
  - `law-pipeline/raw_pdfs/` and `law-pipeline/processed/` (pre-anonymization text — PII risk)
  - `.venv/`, `__pycache__/`
- **Pre-push safety:** grep staged files for API-key-shaped strings; confirm no `.env` in git history.
- **Root README rewrite:** product description, architecture diagram, run instructions (backend, seeding, site, OS), data provenance note.
- Commit in a few logical chunks, push to `origin main`.

## Out of Scope (later work)

- Scaling ARN decisions beyond 10 (pipeline exists, separate run)
- Deployment/hosting, real domain
- Auth on backend or OS
- Automated tests
- Spam protection on the form
