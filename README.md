# Swiftclaim

Swiftclaim.se — en svensk tjänst som hjälper fastighetsägare att få ut hela
försäkringsersättningen de har rätt till efter skador. Insurance companies
systematically underpay; Swiftclaim fights back with Försäkringsavtalslagen
(FAL), ARN precedents, and LLM-generated legal arguments.

## How it works

```
site/        Public marketing site + claim intake form (static Swedish HTML)
   │  POST /api/cases
   ▼
backend/     FastAPI + SQLite — cases, laws, ARN decisions, RAG search,
   │         LLM draft generation (DeepSeek)
   ▼
os/          Internal claims dashboard (vanilla JS, localStorage) — pulls
             cases from the backend, scores them, runs legal research and
             drafts responses

law-pipeline/         Python pipeline: scrapes ARN decisions + Swedish
                      statutes, anonymizes via LLM, writes the vault
swiftclaim-obsidian/  Legal knowledge vault: 1,289 statute paragraphs
                      (12 SFS laws), anonymized ARN decisions, concept notes
```

## Run locally

Requirements: Python 3.9+, API keys in `backend/.env`
(`DEEPSEEK_API_KEY`, `VOYAGE_API_KEY`).

```bash
# 1. Backend
cd backend && pip install -r requirements.txt && python run.py
# → http://localhost:8000 (docs at /docs)

# 2. Import ARN decisions from the vault
curl -X POST http://localhost:8000/api/arn/import -H "Content-Type: application/json" -d '{}'

# 3. Serve site + OS from the repo root
python3 -m http.server 8080
# Site: http://localhost:8080/site/landing_v2.html
# OS:   http://localhost:8080/os/index.html
```

Submit a claim via the form at `landing_v2.html#anmal` — it lands in the
backend and appears in the OS dashboard (auto-sync on load, or the
"Synka från backend" button). From a case in the OS you can run semantic
search over the legal vault and generate a draft response letter.

The first RAG query builds the Voyage embeddings index over the vault
(`law-pipeline/.embeddings.json`, ~18 MB, not in git).

## Data provenance

- **Statutes** scraped from lagen.nu / riksdagen.se (public law).
- **ARN decisions** are public board decisions, LLM-anonymized before storage
  (GDPR caution). Raw PDFs and pre-anonymization text never enter git.

## Design

`site/DESIGN_GUIDELINES.md` is the design contract for all public pages.
