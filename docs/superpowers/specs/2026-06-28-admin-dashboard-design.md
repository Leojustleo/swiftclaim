# Admin Dashboard — Design Spec
**Date:** 2026-06-28  
**Status:** Approved

## Overview

A lightweight admin dashboard for Swiftclaim operators to view incoming claim intake submissions and an AI-generated scorecard per case. Protected by a single shared password. Built as a static HTML page served by the existing FastAPI backend.

---

## Architecture

**Approach:** Extend existing FastAPI backend (port 8000) with auth and admin endpoints. Serve static admin HTML from a new `admin/` directory mounted as StaticFiles.

**New files:**
- `backend/app/auth.py` — password check, JWT creation/validation
- `backend/app/scoring.py` — LLM scorecard generator (claim strength, priority, win probability, recommended action)
- `admin/login.html` — password entry page
- `admin/index.html` — main dashboard
- `admin/app.js` — fetch calls, rendering, localStorage token management
- `admin/styles.css` — Swiftclaim design tokens (navy/yellow/white)

**Changes to existing files:**
- `backend/app/models.py` — add `scorecard` TEXT column (JSON) to `Case` table
- `backend/app/main.py` — mount `admin/` as StaticFiles, register auth + admin routers
- `backend/.env` — add `ADMIN_PASSWORD` and `SECRET_KEY` vars

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

## AI Scorecard

Generated on first view of a case (lazy). Cached in `cases.scorecard` JSON column. Can be regenerated via button.

**Scoring logic (`backend/app/scoring.py`):**
1. Fetch case fields from DB
2. RAG: retrieve top 3 ARN precedents matching `damage_category` via `search_vault()`
3. Call LLM (DeepSeek → kimi-k2.6 fallback via `llm.py`) with structured prompt
4. Validate JSON response, write to `cases.scorecard`

**Scorecard output schema:**
```json
{
  "claim_strength": 78,
  "win_probability": "68%",
  "priority": "high",
  "recommended_action": "Begär omprövning med ARN-stöd — ARN 2020-08495 är direkt jämförbar...",
  "key_factors": [
    "Underbetalt med 85 000 kr — stor återvinningspotential",
    "If förlorar ofta i ARN vid vattenskador utan fullständig besiktning",
    "Skadedatum och beskrivning väldokumenterade"
  ]
}
```

**Priority thresholds:** `claim_strength >= 70` → high, `40–69` → medium, `< 40` → low.

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
