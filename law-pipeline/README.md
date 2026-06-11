# ARN → Obsidian Pipeline

Scrapes Swedish ARN (Allmänna reklamationsnämnden) insurance decisions,
extracts text from PDFs, processes them through Claude for anonymization
and structuring, and writes a fully linked Obsidian vault.

## What it builds

```
obsidian_vault/
├── ARN/
│   ├── ARN 2021-17230.md   ← one file per decision (anonymized, structured)
│   ├── ARN 2022-10-24.md
│   └── ...
├── Lagstiftning/
│   ├── FAL 4 kap 6 §.md    ← auto-created stubs (fill in from Riksdagen API)
│   └── Avtalslagen 36 §.md
├── Koncept/
│   ├── Säkerhetsföreskrift.md   ← legal concept stubs
│   └── Nedsättningsrätt.md
├── Index/
│   └── Försäkring.md       ← auto-generated category index
└── summary.json            ← machine-readable index of all decisions
```

Each decision file has:
- YAML frontmatter (outcome, insurer, damage type, legal basis, keywords)
- Full anonymized case text in Swedish
- `[[wiki-links]]` to statutes, concepts, and related cases
- Outcome label (consumer_won / consumer_lost / partially_won)

## Setup

### 1. Install dependencies

```bash
pip install httpx pdfplumber anthropic rich
```

### 2. Configure

Edit `config.py`:
```python
ANTHROPIC_API_KEY = "sk-ant-..."   # or set env var ANTHROPIC_API_KEY
OBSIDIAN_VAULT    = Path("/path/to/your/vault")   # where to write files
```

Or use environment variables:
```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

### 3. Run

```bash
# Full run (scrape + extract + process + write)
python main.py

# Test with just 5 decisions first
python main.py --limit 5

# Skip re-downloading if you already have PDFs
python main.py --skip-scrape

# Only insurance decisions
python main.py --category forsakring
```

## Connect to Obsidian

1. Open Obsidian
2. **Open folder as vault** → select `obsidian_vault/` directory
3. Install the **Dataview** plugin for querying decisions:

```dataview
TABLE outcome, insurer, damage_type, date
FROM "ARN"
WHERE outcome = "consumer_won"
SORT date DESC
```

4. Install **Graph view** — the `[[wiki-links]]` automatically build
   a citation graph showing which statutes and concepts appear most.

## Incremental updates

Re-run `python main.py` at any time. Already-downloaded PDFs are skipped
automatically. New decisions from ARN are picked up and added to the vault.

## GDPR compliance

The LLM layer strips all personal data (names, addresses, personnummer)
before writing to disk. Raw PDFs are stored locally only as source material.
The vault contains only anonymized data safe for commercial use.

## Architecture

```
ARN website
    │
    ▼
src/scraper.py          — httpx, finds & downloads PDFs from arn.se
    │
    ▼
src/extractor.py        — pdfplumber, extracts clean text from PDFs
    │
    ▼
src/processor.py        — Anthropic API (Claude), anonymizes + structures
    │
    ▼
src/vault.py            — writes .md files + stubs + indexes to Obsidian vault
```

## Extending

- **Add Riksdagen statutes**: fetch from `data.riksdagen.se` and populate
  the `Lagstiftning/` stubs with actual law text
- **Add HD case law**: scrape lagrummet.se, process through same pipeline,
  write to `HD/` folder with cross-links to ARN decisions
- **LLM querying**: use the vault as a RAG knowledge base — query with
  "find all cases where insurer cited säkerhetsföreskrift and consumer won"
