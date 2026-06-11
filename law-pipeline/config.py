"""
ARN Pipeline Configuration
Edit these values before running.
"""
from pathlib import Path

# ─── OpenRouter (LLM via OpenAI-compatible API) ───────────────────────────────
OPENROUTER_API_KEY = "YOUR_API_KEY_HERE"   # or set env var OPENROUTER_API_KEY
# OpenRouter model ID format: <provider>/<model>
# Kimi K2.6: 262K context, ~4x cheaper than Claude Sonnet, strong on multilingual.
# Swap to anthropic/claude-sonnet-4.5 or anthropic/claude-opus-4.7 for higher quality runs.
CLAUDE_MODEL       = "deepseek-chat"

# ─── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR         = Path(__file__).parent
RAW_PDF_DIR      = BASE_DIR / "raw_pdfs"            # downloaded PDFs land here
PROCESSED_DIR    = BASE_DIR / "processed"           # extracted text as .txt
OBSIDIAN_VAULT   = BASE_DIR.parent / "swiftclaim-obsidian"    # final .md files

# Sub-folders inside the vault
VAULT_ARN        = OBSIDIAN_VAULT / "ARN"          # one file per decision
VAULT_LAW        = OBSIDIAN_VAULT / "Lagstiftning" # statute section stubs
VAULT_CONCEPTS   = OBSIDIAN_VAULT / "Koncept"      # legal concept stubs
VAULT_INDEX      = OBSIDIAN_VAULT / "Index"        # category index pages

# ─── Scraper ──────────────────────────────────────────────────────────────────
ARN_BASE_URL       = "https://www.arn.se"
ARN_DECISIONS_PAGE = "/om-arn/vagledande-beslut/"
ARN_PDF_BASE       = "https://www.arn.se/globalassets/extern/pdfer"

# Only scrape these categories (None = scrape all)
# Insurance proper + property (Bo/Bostad) + Motor & Resor for broader insurance jurisprudence
CATEGORY_FILTER = ["Försäkring", "Forsakring", "Bo", "Bostad", "Motor", "Resor"]

RATE_LIMIT_SECONDS = 1.5   # be polite to the public authority
MAX_CONCURRENT     = 3     # parallel downloads
USER_AGENT         = "LegalResearchBot/1.0 (property insurance research; update with your contact)"

# ─── LLM Processing ───────────────────────────────────────────────────────────
# Minimum text length to attempt LLM processing (skip empty/corrupt PDFs)
MIN_TEXT_LENGTH = 200

# How many decisions to process in one run (None = all)
PROCESS_LIMIT = None
