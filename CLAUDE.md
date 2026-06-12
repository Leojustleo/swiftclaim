# Swiftclaim — Agent Context

## Vision

Swiftclaim.se helps Swedish property owners get the **full insurance payout** they are entitled to after damage claims. Insurance companies systematically underpay — Swiftclaim fights back by weaponizing **Försäkringsavtalslagen (FAL)**, **ARN precedents**, and **LLM-generated legal arguments**.

En svensk tjänst som hjälper fastighetsägare att få ut hela försäkringsersättningen de har rätt till efter skador.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  site/  ──→  Public marketing site (static HTML/CSS)    │
│                 landing_v2.html, om-oss.html             │
└─────────────────────────────────────────────────────────┘
                            │
                            ▼  (customer submits claim)
┌─────────────────────────────────────────────────────────┐
│  os/   ──→  Internal claims dashboard (vanilla JS)      │
│                 IndexedDB persistence, case mgmt         │
└─────────────────────────────────────────────────────────┘
                            │
                            ▼  (case data + legal refs)
┌─────────────────────────────────────────────────────────┐
│  backend/  ──→  FastAPI (port 8000) + SQLite            │
│     app/main.py       API: CRUD, RAG, LLM drafting      │
│     app/rag.py        Voyage embeddings + semantic search│
│     app/law_importer.py  Firecrawl→lagen.nu law fetcher  │
└─────────────────────────────────────────────────────────┘
                            │
                            ▼  (reads vault for RAG)
┌─────────────────────────────────────────────────────────┐
│  law-pipeline/  ──→  ARN decision ingestion              │
│     scraper.py      ARN.se → PDFs                        │
│     extractor.py    PDFs → text                          │
│     processor.py    LLM anonymize + structure (OpenRouter)│
│     vault.py        → swiftclaim-obsidian/ARN/           │
│     fill_stubs.py   lagen.nu → swiftclaim-obsidian/Lag/  │
│     query.py        RAG demo (Voyage + Claude)           │
└─────────────────────────────────────────────────────────┘
                            │
                            ▼  (writes to)
┌─────────────────────────────────────────────────────────┐
│  swiftclaim-obsidian/  ──→  Legal knowledge vault        │
│     ARN/          10 anonymized ARN decisions (.md)      │
│     Lagstiftning/ 35 Swedish statute paragraphs (.md)    │
│     Koncept/       7 legal concept stubs (.md)           │
│     Index/         Auto-generated category indexes       │
│     summary.json   Machine-readable index of all ARN     │
└─────────────────────────────────────────────────────────┘
```

## Tech Stack

| Component | Tech |
|-----------|------|
| Public site | Static HTML/CSS, Swedish content, no framework |
| OS Dashboard | Vanilla JS, IndexedDB, CSS custom properties |
| Backend API | Python 3, FastAPI, Uvicorn, SQLAlchemy, SQLite |
| LLM | DeepSeek direct → deepseek-chat (drafts), OpenRouter → moonshotai/kimi-k2.6 (pipeline) |
| Embeddings | Voyage AI (voyage-3) |
| Scraping | httpx (ARN.se, lagen.nu, riksdagen.se), Firecrawl MCP (lagen.nu) |
| Knowledge base | Obsidian vault: markdown + YAML frontmatter + `[[wiki-links]]` |
| MCP | Playwright (browser), Firecrawl (web scraping) |

## Design System

**Always consult `site/DESIGN_GUIDELINES.md` before making any frontend changes.** It contains the full design system extracted from `landing_v2.html`: color palette, typography, components, animations, responsive breakpoints, and file checklist. All 7 HTML pages in `site/` follow these guidelines.

Key rules:
- All "Anmäl skada" buttons: `#f7d154` yellow with dark text
- Decorative squares (`.pixel`, `.eyebrow::before`): `#112D4E` navy
- Dark surfaces (nav, footer): `#112D4E` navy glass
- Card backgrounds: `#DBE2EF` blue-grey
- Italic emphasis: `<span class="serif-em">` (Fraunces)
- Never hardcode colors; use CSS variables from the guidelines

## Conventions

- **Swedish** for public-facing content (site/, os/ UI)
- **English** for code, comments, backend logic
- **Vault entries** use YAML frontmatter + `[[wiki-links]]` for cross-refs
- **ARN decisions**: `case_id`, `category`, `date`, `outcome`, `insurer`, `damage_type`, `legal_basis`, `keywords`
- **Lagstiftning**: `type: lagrum`, `statute`, `sfs`, `full_name`, `source_url`
- **Python**: `from __future__ import annotations`, type hints, `httpx` for HTTP
- **No frameworks** for frontend — keep it simple static/vanilla
- **GDPR-aware**: pipeline strips all PII via LLM before writing to disk

## Run Commands

```bash
# Backend API
python backend/run.py                          # → http://localhost:8000

# Seed database from Obsidian vault
python backend/seed.py

# ARN pipeline (full run)
cd law-pipeline && source .venv/bin/activate
python main.py                                 # scrape → extract → process → write
python main.py --limit 50 --skip-scrape        # process only

# Fill law stubs from lagen.nu
python fill_stubs.py

# RAG query demo
python query.py "din fråga på svenska"
python query.py --reindex "..."                # rebuild embedding index

# Full law scraping into vault
python scrape_laws_to_vault.py                 # (new) scrape all SFS to Lagstiftning/

# Public site — open in browser
open site/landing_v2.html

# OS Dashboard — open in browser
open os/index.html
```

## Key Files

| File | Purpose |
|------|---------|
| `backend/app/main.py:1` | FastAPI app: `/cases`, `/drafts`, `/laws`, `/rag/search` |
| `backend/app/rag.py:1` | Voyage embeddings + semantic search over vault |
| `backend/app/law_importer.py:1` | Firecrawl integration for lagen.nu, SFS_MAP, Riksdagen API |
| `backend/app/models.py:1` | SQLAlchemy ORM: Case, ARNDecision, LawSection, Draft |
| `backend/app/schemas.py:1` | Pydantic schemas for API request/response |
| `law-pipeline/main.py:1` | Pipeline orchestrator |
| `law-pipeline/src/scraper.py:1` | ARN.se decision PDF scraper |
| `law-pipeline/src/processor.py:1` | LLM anonymization + structuring |
| `law-pipeline/src/vault.py:1` | Writes processed decisions to Obsidian vault |
| `law-pipeline/fill_stubs.py:1` | Fills law stubs from lagen.nu HTTP |
| `law-pipeline/scrape_laws_to_vault.py:1` | Batch Firecrawl scraper: lagen.nu → Obsidian vault |
| `os/app.js:1` | Claims dashboard application logic |
| `os/api.js:1` | Frontend-backend bridge: API calls + schema translation |
| `.mcp.json` | MCP server config (Playwright, Firecrawl) |

## MCP Tools

- **Playwright** — Browser automation: navigate, click, screenshot, extract text
- **Firecrawl** — Web scraping: `firecrawl_scrape` (single URL), `firecrawl_batch_scrape` (multiple URLs), `firecrawl_map` (discover URLs), `firecrawl_search` (web search)

## Environment

```
backend/.env          — DEEPSEEK_API_KEY, VOYAGE_API_KEY
law-pipeline/.env     — OPENROUTER_API_KEY, VOYAGE_API_KEY
```

## Running Log

### 2026-05-31
- Added Firecrawl MCP server to `.mcp.json` (local `localhost:3002`)
- Created `CLAUDE.md` — project soul + agent context
- Created `law-pipeline/scrape_laws_to_vault.py` — batch scrapes all 12 SFS statutes from lagen.nu via Firecrawl, parses individual paragraphs, writes clean `.md` to vault
- **Scraping results (v1)**: 12 full-law files + 1,288 individual paragraph files
- **Fix**: Rewrote paragraph parser to capture ordered/unordered list items and sub-stycken (`S` anchors) — 134 truncated files repaired
- **Cleanup**: Removed 15 problematic files (12 empty stubs, 2 HTML-contaminated, 1 duplicate `Avtalslagen 36 §`)
- **Final vault**: 12 full-law files + 1,276 paragraph files + 1 index = **1,289 total .md files** in Lagstiftning/
- **Quality**: 100% clean — zero HTML artifacts, zero stubs, zero truncations
- Coverage:
  - FAL (2005:104): 256 paragraphs, full coverage
  - Avtalslagen (1915:218): 41 paragraphs
  - Skadeståndslagen (1972:207): 37 paragraphs
  - Distansavtalslagen (2005:59): 43 paragraphs
  - Konsumentköplagen (1990:932): 28 paragraphs
  - Konsumenttjänstlagen (1985:716): 63 paragraphs
  - Konsumentförsäkringslagen (1980:38): 43 paragraphs (upphävd)
  - Konsumentavtalsvillkorslagen (1994:1512): 35 paragraphs
  - Trafikskadelagen (1975:1410): 50 paragraphs
  - Jordabalken (1970:994): 492 paragraphs
  - Bostadsrättslagen (1991:614): 156 paragraphs
  - Paketreselagen (2018:1217): 50 paragraphs
- Next priorities:
  - Rebuild Voyage embeddings index (`query.py --reindex`)
  - Update `summary.json` with new statute data
  - Add Hyreslagen sections (JB 12 kap) as a separate statute
  - Run full ARN pipeline for more decisions

### 2026-05-31 (PM)
- **Frontend-backend integration**: Created `os/api.js` bridge module connecting the OS Dashboard to the FastAPI backend
  - Auto-detects backend availability at `localhost:8000` with graceful fallback
  - Schema translation between OS's nested case model and backend's flat SQL schema
  - Functions: `searchLaw(query)`, `generateDraft(caseItem)`, `importCase(item)`, `getCases()`, `getARN()`
- **UI additions** to OS Dashboard (both `index.html` and `app.js`):
  - **Legal Research panel** in case detail view — "Rättskunskap" subpanel with 3 buttons:
    - "Sök relevant lagstiftning" — RAG search over entire vault (1,289 law files + ARN precedents)
    - "Generera juridiskt utkast" — LLM draft generation via DeepSeek (auto-imports case to backend first)
    - "Synka till backend" — pushes local case to SQLite DB
  - **Vault search in Knowledge view** — free-text search over the legal knowledge base
  - Results display with color-coded badges (statutes=green, precedents=orange), relevance scores, and text previews
- **CSS additions**: Legal research panel styles in `styles.css` (~100 new lines)
- **Voyage embeddings rebuilt**: 1,305 notes re-indexed after vault expansion
- **Verified**: Backend RAG search returns correct results (`FAL 4 kap 6 §` as top hit for "säkerhetsföreskrift nedsättning")

### 2026-06-12
- **Draft generation v2** (spec + plan in `docs/superpowers/`): replaced blocking single-shot `/api/draft` with async 4-stage pipeline (plan → retrieve → draft → verify) in `backend/app/draft_ai.py`
  - `POST /api/draft` returns 202 + job id; poll `GET /api/draft-jobs/{id}`; stage snapshots stored on the job row
  - Citation verification (`backend/app/verify.py`): lagrum normalizer + resolution against vault/DB; unverified → LLM repair pass → still bad = draft `needs_review` with `flagged_citations`
  - Shared LLM client (`backend/app/llm.py`): DeepSeek → OpenRouter kimi-k2.6 fallback chain, JSON schema validation, every call logged to `llm_calls` table
  - **PII guard**: customer name/email/phone/address replaced with `[KUND]`/`[EPOST]`/`[TELEFON]`/`[ADRESS]` before any LLM call, substituted back post-verify
  - **Vault Q&A**: `POST /api/ask` — grounded answers with verified sources + lagen.nu links; ask boxes in OS (case panel + Knowledge view)
  - RAG upgrades: in-memory singleton index (was: ~1,800 files + 21MB JSON reloaded per query), `search_vault(dirs, k, min_score)`, whole-statute files (>15k chars) excluded from retrieval
  - Evals: `backend/evals/run_evals.py` + 10-case golden set; smoke run 2/2: 100% completion, 100% citation validity, 100% expected-ref hit
  - Tests: `cd backend && python3 -m pytest tests/` (14 tests, pure functions only — no live calls)
