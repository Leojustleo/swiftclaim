# Admin Dashboard — Design Spec
**Date:** 2026-06-28  
**Status:** Approved

## Overview

A lightweight admin dashboard for Swiftclaim operators to view incoming claim intake submissions and an AI-generated scorecard per case. Protected by a single shared password. Built as a static HTML page served by the existing FastAPI backend.

Scorecard uses the **LLM Wiki pattern** (Karpathy, 2026) powered by **DeepSeek V4 Pro** (1M context). Existing Voyage embedding RAG for the OS dashboard Q&A and draft generation is unchanged.

---

## Architecture

**Approach:** Extend existing FastAPI backend (port 8000) with auth and admin endpoints. Serve static admin HTML from a new `admin/` directory mounted as StaticFiles.

**New files:**
- `backend/app/auth.py` — password check, JWT creation/validation
- `backend/app/wiki_index.py` — builds + maintains compiled ARN wiki index from `swiftclaim-obsidian/ARN/`
- `backend/app/scoring.py` — LLM Wiki scorecard generator using DeepSeek V4 Pro
- `admin/login.html` — password entry page
- `admin/index.html` — main dashboard
- `admin/app.js` — fetch calls, rendering, localStorage token management
- `admin/styles.css` — Swiftclaim design tokens (navy/yellow/white)

**Changes to existing files:**
- `backend/app/models.py` — add `scorecard` TEXT column (JSON) to `Case` table
- `backend/app/main.py` — mount `admin/` as StaticFiles, register auth + admin routers
- `backend/.env` — add `ADMIN_PASSWORD`, `SECRET_KEY`, `DEEPSEEK_V4_API_KEY`

**Unchanged:**
- `backend/app/rag.py` — Voyage embedding RAG (OS dashboard Q&A + draft generation)
- `backend/app/draft_ai.py`, `qa_ai.py`, `llm.py` — untouched

---

## Auth

Single shared password stored in `backend/.env` as `ADMIN_PASSWORD`.

**Flow:**
1. `admin/login.html` prompts for password
2. `POST /api/auth/login` receives `{ password }`, compares to `ADMIN_PASSWORD`
3. On match: returns `{ token: "<signed JWT>" }` with 8h expiry, signed with `SECRET_KEY`
4. Frontend stores token in `localStorage`
5. All `/api/admin/*` requests include `Authorization: Bearer <token>` header
6. Backend dependency `require_admin_token()` validates on every admin request
7. 401 response → frontend clears token, redirects to login

No user table. No per-user accounts. One shared token for the whole team.

---

## Admin API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/auth/login` | Validate password, return JWT |
| GET | `/api/admin/cases` | Paginated list of all cases (with cached scorecard) |
| GET | `/api/admin/cases/{id}` | Single case detail + scorecard |
| POST | `/api/admin/cases/{id}/score` | (Re)generate AI scorecard for a case |

**Query params for `GET /api/admin/cases`:**
- `priority` — filter by high/medium/low
- `damage_category` — filter by damage type
- `status` — filter by case status
- `page`, `limit` — pagination (default limit: 50)

---

## AI Scorecard — LLM Wiki Pattern

Generated on first view of a case (lazy). Cached in `cases.scorecard` JSON column. Can be regenerated via button.

### Retrieval Strategy

**LLM Wiki** (not embedding RAG) powers the scorecard. The ARN corpus (36 decisions) is pre-compiled into a single index markdown file by `wiki_index.py`. DeepSeek V4 Pro's 1M context window loads the full index + selected full decision texts in one call.

**Why LLM Wiki over RAG here:**
- 36 ARN decisions fit entirely in context — no chunking loss
- Legal scoring needs full decision text, not truncated chunks
- Cross-references (`[[wiki-links]]`) between decisions and law sections are preserved
- No embedding cost or latency for this corpus

**Voyage embedding RAG remains** for OS dashboard (`/api/ask`, `/api/draft`) where the corpus is 1,489 law section files — too large for LLM Wiki.

### `wiki_index.py` — ARN Index Builder

Reads all 36 `.md` files from `swiftclaim-obsidian/ARN/`, extracts YAML frontmatter, and writes a compiled index to `backend/data/arn_wiki_index.md`:

```markdown
# ARN Wiki Index — 36 beslut

## ARN 2020-08495
- Kategori: försäkring / vattenskada
- Utfall: consumer_won
- Bolag: If
- Belopp: 120 000 kr
- Rättslig grund: FAL 4 kap 6 §, FAL 6 kap 1 §
- Nyckelord: vattenskada, åldersavdrag, besiktning
- Sammanfattning: Konsument vann efter att If nekat ersättning för vattenskada med hänvisning till åldersavdrag. ARN fann att bolaget inte uppfyllt sin utredningsskyldighet.

## ARN 2019-04350
...
```

Index is rebuilt on backend startup if `swiftclaim-obsidian/ARN/` has changed (mtime check). Cached on disk.

### `scoring.py` — Scorecard Generation

**Step 1 — Index pass (DeepSeek V4 Pro, ~2k tokens):**
Send ARN wiki index + case summary → ask model to identify the 3–5 most relevant ARN decision IDs.

**Step 2 — Scoring pass (DeepSeek V4 Pro, ~15k tokens):**
Load full markdown text of the identified decisions + case fields → ask model to produce scorecard JSON.

**Prompt structure (step 2):**
```
Du är en svensk försäkringsjurist. Bedöm följande ärende mot ARN-praxis.

## Ärende
[case fields: damage_category, insurance_company, claim_amount, insurer_decision, insurer_reason, description]

## Relevanta ARN-beslut
[full markdown of 3–5 selected decisions]

## Uppgift
Returnera ett JSON-objekt med följande fält: claim_strength (0–100), win_probability (procent som sträng), priority (high/medium/low), recommended_action (sträng, max 2 meningar, hänvisa till specifikt ARN-beslut), key_factors (lista med 3 punkter).
```

**Model:** `deepseek-v4-pro` via DeepSeek API (`DEEPSEEK_V4_API_KEY`). No fallback needed — if call fails, scorecard stays null, user can retry.

**Scorecard output schema:**
```json
{
  "claim_strength": 78,
  "win_probability": "68%",
  "priority": "high",
  "recommended_action": "Begär omprövning med ARN-stöd — ARN 2020-08495 (vattenskada, If, konsument vann) är direkt jämförbar. Bifoga besiktningsprotokoll och kräv specificerad motivering till nedsättningen.",
  "key_factors": [
    "Underbetalt med 85 000 kr — stor återvinningspotential",
    "If förlorar ofta i ARN vid vattenskador utan fullständig besiktning",
    "Skadedatum och beskrivning väldokumenterade"
  ],
  "arn_references": ["ARN 2020-08495", "ARN 2019-04350"]
}
```

**Priority thresholds:** `claim_strength >= 70` → high, `40–69` → medium, `< 40` → low.

**Cost per scorecard:** ~15k tokens × $0.44/M = ~$0.007. Negligible.

### Retrieval Strategy Summary

| Use case | Method | Model |
|---|---|---|
| Admin scorecard | LLM Wiki (ARN index + full docs) | DeepSeek V4 Pro |
| OS Q&A (`/api/ask`) | Voyage embedding RAG | DeepSeek / kimi-k2.6 |
| Draft generation (`/api/draft`) | Voyage embedding RAG | DeepSeek / kimi-k2.6 |

---

## UI

**`admin/login.html`:**
- Centered card on navy background
- Swiftclaim logo + "Admin" label
- Single password field + "Logga in" button
- Wrong password → red inline error
- Correct → store token in `localStorage`, redirect to `index.html`

**`admin/index.html` — two-column layout:**

*Left panel (460px, fixed):*
- Header: "Ärenden · N st"
- Filter pills: Alla / Hög prio / by damage category / Avslaget
- Scrollable case list — each row shows:
  - Case ID, customer name, insurer + damage type + date
  - Priority badge (🔴 Hög / 🟡 Medel / 🟢 Låg)
  - Claim strength bar (0–100) with numeric label
- Click row → loads detail in right panel, highlights active row

*Right panel (flex: 1):*
- Case header: ID + date, customer name, insurer + damage type + decision
- "↻ Generera om scorecard" button (top right)
- **AI Scorecard card** (dark navy background):
  - Three metrics: Ärendestyrka (0–100 + bar), Vinstchans (%), Prioritet badge
  - Recommended action block
  - Key factors checklist
- Two-column info cards: Kundinformation + Skadeinformation
- Full-width description card
- Amount comparison: Yrkat / Erbjudet / Diff (diff in red)

**No external JS dependencies.** Vanilla JS, CSS custom properties, `fetch`. Same design tokens as `site/` and `os/`.

---

## Scorecard Generation Trigger

- Generated **lazily** on first click of a case row (if `scorecard` is null)
- While generating: skeleton loader shown in scorecard card
- On error: "Kunde inte generera scorecard" with retry button
- Regeneration button always visible, re-calls `POST /api/admin/cases/{id}/score`

---

## Data Flow

```
User clicks case row
  → GET /api/admin/cases/{id}
  → if scorecard null: POST /api/admin/cases/{id}/score (scoring.py → LLM → cache)
  → render scorecard + case detail
```

---

## Out of Scope

- Email notifications
- Case status updates from admin UI (read-only for now)
- Multiple admin user accounts
- Export/CSV download
- ARN database browser (separate future feature)
- LLM Wiki for Lagstiftning (1,489 files — too large; keep Voyage RAG)
- Automatic ARN wiki index rebuild on vault changes (manual trigger only for now)
