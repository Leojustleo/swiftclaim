# Swiftclaim MVP End-to-End Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A customer submits a real claim on the public site → it lands in the backend → appears in the OS dashboard → Swiftclaim generates a legally grounded draft letter from real statutes + ARN precedents. Whole project pushed to GitHub.

**Architecture:** Static site form POSTs JSON to local FastAPI (`localhost:8000`). OS dashboard pulls backend cases through its existing intake-analysis path (`analyzeIntake` → `createCaseFromPayload`) so every synced case gets a real scorecard. Fake seed data removed. Vault + pipeline un-gitignored and published.

**Tech Stack:** Vanilla HTML/CSS/JS (site, os), FastAPI + SQLite (backend), Voyage embeddings + OpenRouter deepseek-chat (RAG/drafts).

**Spec:** `docs/superpowers/specs/2026-06-11-mvp-end-to-end-design.md`

No automated test suite (explicitly out of scope in spec). Each task ends with a manual verification command and expected output.

---

### Task 1: Fix backend LLM endpoint

**Files:**
- Modify: `backend/app/main.py:50-51`

The code posts to `api.deepseek.com` but the env var is an OpenRouter key. Point it at OpenRouter.

- [ ] **Step 1: Edit constants**

Replace:
```python
OR_URL = "https://api.deepseek.com/v1/chat/completions"
CHAT_MODEL = "deepseek-chat"
```
with:
```python
OR_URL = "https://openrouter.ai/api/v1/chat/completions"
CHAT_MODEL = "deepseek/deepseek-chat"
```

- [ ] **Step 2: Verify backend boots**

Run: `cd /Users/leo-mac/claude-code/Swiftclaim/backend && python run.py` (background), then
`curl -s http://localhost:8000/api/status`
Expected: `{"status":"ok","service":"Swiftclaim"}`

- [ ] **Step 3: Commit**

```bash
git add backend/app/main.py
git commit -m "fix(backend): point draft generation at OpenRouter, not DeepSeek direct"
```
(Note: backend/ is untracked — this commit adds whole backend/ in Task 8 instead if cleaner; minimum here is the file edit. If backend/ not yet tracked, defer commit to Task 8.)

---

### Task 2: Seed backend with real data

**Files:** none (runtime state, `backend/data/swiftclaim.db` is gitignored)

- [ ] **Step 1: Import the 10 anonymized ARN decisions from the vault**

Run: `curl -s -X POST http://localhost:8000/api/arn/import -H "Content-Type: application/json" -d '{}'`
Expected: `{"imported":10}`

- [ ] **Step 2: Confirm laws + ARN queryable**

Run: `curl -s http://localhost:8000/api/arn | python3 -c "import json,sys; print(len(json.load(sys.stdin)))"`
Expected: `10`

- [ ] **Step 3: Smoke-test RAG over real vault**

Run:
```bash
curl -s -X POST http://localhost:8000/api/search/law -H "Content-Type: application/json" \
  -d '{"question": "nedsättning av ersättning säkerhetsföreskrift", "top_k": 3}' | python3 -m json.tool | head -20
```
Expected: hits array, top hit referencing FAL (e.g. `FAL 4 kap 6 §`), scores ≈ 0.5+.

---

### Task 3: Site intake form (`site/landing_v2.html`)

**Files:**
- Modify: `site/landing_v2.html` (3 insertions: section markup before `#anmal` CTA strip at line ~1711, CSS before `</style>` at line ~1057, script before existing `<script>` at line ~1789)

- [ ] **Step 1: Move `id="anmal"` and insert form section**

Change line 1711 `<section class="cta-dark" id="anmal">` → `<section class="cta-dark">`.

Insert BEFORE that section:

```html
<!-- ── Anmäl skada ───────────────────────────────────── -->
<section class="claim-intake" id="anmal">
  <div class="wrap">
    <div class="sec-head">
      <div class="sec-head__label"><div class="eyebrow">Anmäl skada</div></div>
      <div class="sec-head__title"><h2>Berätta om din <span class="serif-em">skada</span></h2></div>
      <div class="sec-head__meta">Kostnadsfri första bedömning. Vi går igenom ditt ärende och återkommer inom en arbetsdag.</div>
    </div>

    <form class="claim-form" id="claimForm">
      <div class="claim-form__grid">
        <label>Namn *<input name="customerName" required placeholder="För- och efternamn" /></label>
        <label>E-post *<input name="email" type="email" required placeholder="namn@exempel.se" /></label>
        <label>Telefon<input name="phone" type="tel" placeholder="+46 70 123 45 67" /></label>
        <label>Ort<input name="city" placeholder="Stockholm" /></label>
        <label>Bostadstyp
          <select name="propertyType">
            <option>Villa</option><option>Bostadsrätt</option><option>Hyresrätt</option><option>Fritidshus</option>
          </select>
        </label>
        <label>Försäkringsbolag *
          <select name="insuranceCompany" required>
            <option value="">Välj bolag…</option>
            <option>Folksam</option><option>Trygg-Hansa</option><option>If</option><option>Länsförsäkringar</option><option>Dina Försäkringar</option><option>Gjensidige</option><option>ICA Försäkring</option><option>Hedvig</option><option>Moderna Försäkringar</option><option>Protector</option><option>Annat</option>
          </select>
        </label>
        <label>Typ av skada *
          <select name="damageCategory" required>
            <option value="">Välj skadetyp…</option>
            <option>Vattenskada</option><option>Brand- eller rökskada</option><option>Stormskada</option><option>Stöld- eller inbrottsskada</option><option>Mögel eller fuktskada</option><option>Vitvaruskada</option><option>Ansvar bostadsrätt/hyresrätt</option><option>Annan egendomsskada</option>
          </select>
        </label>
        <label>Skadedatum<input name="incidentDate" type="date" /></label>
        <label>Yrkat belopp, kr<input name="claimedAmount" type="number" min="0" step="1000" placeholder="150000" /></label>
        <label>Var står du i processen?
          <select name="currentStage">
            <option>Ej inskickat</option>
            <option>Inskickat till försäkringsbolag</option>
            <option>Beslut mottaget</option>
            <option>Avslaget</option>
            <option>Underbetalt</option>
            <option>Överklagan pågår</option>
          </select>
        </label>
      </div>

      <label class="claim-form__full">Beskriv skadan *
        <textarea name="description" rows="6" required placeholder="Vad hände, när, och vad har försäkringsbolaget sagt hittills?"></textarea>
      </label>

      <div class="claim-form__decision hidden" id="decisionFields">
        <label>Erbjudet belopp, kr<input name="offeredAmount" type="number" min="0" step="1000" /></label>
        <label class="claim-form__full">Bolagets motivering
          <textarea name="insurerReason" rows="3" placeholder="Vad angav bolaget som skäl?"></textarea>
        </label>
      </div>

      <fieldset class="claim-form__evidence">
        <legend>Underlag du har (frivilligt)</legend>
        <label><input type="checkbox" name="evidence" value="Foton" /> Foton</label>
        <label><input type="checkbox" name="evidence" value="Försäkringsbeslut" /> Försäkringsbeslut</label>
        <label><input type="checkbox" name="evidence" value="Försäkringsvillkor" /> Försäkringsvillkor</label>
        <label><input type="checkbox" name="evidence" value="Kvitton" /> Kvitton</label>
        <label><input type="checkbox" name="evidence" value="Offert från entreprenör" /> Offert från entreprenör</label>
        <label><input type="checkbox" name="evidence" value="Skaderapport" /> Skaderapport</label>
      </fieldset>

      <div class="claim-form__actions">
        <button class="btn-pill btn-pill--cta" type="submit" id="claimSubmitBtn">Skicka in ärendet</button>
        <p class="claim-form__error hidden" id="claimError">Kunde inte skicka just nu. Mejla oss på <a href="mailto:hej@swiftclaim.se">hej@swiftclaim.se</a> så återkommer vi.</p>
      </div>
    </form>

    <div class="claim-form__success hidden" id="claimSuccess">
      <h3>Tack! Ditt ärende är <span class="serif-em">mottaget</span>.</h3>
      <p>Ärendenummer: <strong id="claimCaseId"></strong>. Vi går igenom ditt ärende och återkommer inom en arbetsdag.</p>
    </div>
  </div>
</section>
```

- [ ] **Step 2: Insert CSS before `</style>` (line ~1057)**

```css
/* ── Claim intake form ─────────────────────────────── */
.claim-intake { padding: 7rem 0; background: var(--bg); }
.claim-form {
  background: var(--bg-card);
  border: 0.5px solid var(--line);
  border-radius: var(--r-card);
  box-shadow: var(--shadow-soft);
  padding: 2.5rem;
  display: flex; flex-direction: column; gap: 1.5rem;
}
.claim-form__grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1.25rem; }
.claim-form label { display: flex; flex-direction: column; gap: 6px; font-size: 13px; font-weight: 500; color: var(--ink); }
.claim-form input, .claim-form select, .claim-form textarea {
  font: inherit; font-size: 14px; color: var(--ink);
  background: var(--bg);
  border: 0.5px solid var(--line-strong);
  border-radius: 10px;
  padding: 11px 14px;
  outline: none;
}
.claim-form input:focus, .claim-form select:focus, .claim-form textarea:focus { border-color: var(--brand); }
.claim-form textarea { resize: vertical; }
.claim-form__decision { display: grid; grid-template-columns: 1fr 1fr; gap: 1.25rem; padding: 1.25rem; background: var(--bg-deep); border-radius: 10px; }
.claim-form__full, .claim-form__decision .claim-form__full { grid-column: 1 / -1; }
.claim-form__evidence { border: none; display: flex; flex-wrap: wrap; gap: 10px 18px; }
.claim-form__evidence legend { font-size: 12px; font-weight: 500; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); margin-bottom: 10px; }
.claim-form__evidence label { flex-direction: row; align-items: center; gap: 8px; font-weight: 400; font-size: 14px; }
.claim-form__actions { display: flex; align-items: center; gap: 1.5rem; flex-wrap: wrap; }
.claim-form__error { font-size: 14px; color: #8a1f17; }
.claim-form__error a { text-decoration: underline; }
.claim-form__success {
  background: var(--bg-card); border: 0.5px solid var(--line); border-radius: var(--r-card);
  box-shadow: var(--shadow-soft); padding: 2.5rem; text-align: center;
}
.claim-form__success h3 { font-size: 1.4rem; font-weight: 600; letter-spacing: -0.03em; margin-bottom: 0.5rem; }
.claim-form__success p { font-size: 15px; color: var(--ink-2); }
.hidden { display: none !important; }
@media (max-width: 720px) {
  .claim-intake { padding: 4rem 0; }
  .claim-form { padding: 1.5rem; }
  .claim-form__grid, .claim-form__decision { grid-template-columns: 1fr; }
}
```

(`#8a1f17` error red is a deliberate one-off — palette has no error color.)

- [ ] **Step 3: Insert form script as its own `<script>` block just before the existing `<script>` at line ~1789**

```html
<script>
(function () {
  const API = "http://localhost:8000/api";
  const form = document.getElementById("claimForm");
  if (!form) return;

  const stageSelect = form.querySelector('select[name="currentStage"]');
  const decisionFields = document.getElementById("decisionFields");
  const DECISION_STAGES = ["Beslut mottaget", "Avslaget", "Underbetalt", "Överklagan pågår"];

  stageSelect.addEventListener("change", () => {
    decisionFields.classList.toggle("hidden", !DECISION_STAGES.includes(stageSelect.value));
  });

  function caseId() {
    const d = new Date();
    const yymm = String(d.getFullYear()).slice(2) + String(d.getMonth() + 1).padStart(2, "0");
    return `SC-${yymm}-${100 + Math.floor(Math.random() * 900)}`;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();

    const data = new FormData(form);
    const stage = String(data.get("currentStage"));
    const hasDecision = DECISION_STAGES.includes(stage);
    const body = {
      id: caseId(),
      customer_name: String(data.get("customerName") || "").trim(),
      customer_email: String(data.get("email") || "").trim(),
      customer_phone: String(data.get("phone") || "").trim(),
      property_address: String(data.get("city") || "").trim(),
      property_type: String(data.get("propertyType") || ""),
      insurance_company: String(data.get("insuranceCompany") || ""),
      damage_category: String(data.get("damageCategory") || ""),
      damage_description: String(data.get("description") || "").trim(),
      damage_date: String(data.get("incidentDate") || ""),
      claim_amount: Number(data.get("claimedAmount")) || null,
      insurer_decision: stage,
      insurer_amount: hasDecision ? Number(data.get("offeredAmount")) || null : null,
      insurer_reason: hasDecision ? String(data.get("insurerReason") || "").trim() : null,
      tags: data.getAll("evidence").map(String),
    };

    const btn = document.getElementById("claimSubmitBtn");
    const error = document.getElementById("claimError");
    btn.disabled = true;
    error.classList.add("hidden");

    try {
      const r = await fetch(`${API}/cases`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const saved = await r.json();
      form.classList.add("hidden");
      document.getElementById("claimCaseId").textContent = saved.id;
      document.getElementById("claimSuccess").classList.remove("hidden");
    } catch {
      error.classList.remove("hidden");
    } finally {
      btn.disabled = false;
    }
  });
})();
</script>
```

- [ ] **Step 4: Verify**

Serve repo root: `python3 -m http.server 8080` (background, repo root).
Open `http://localhost:8080/site/landing_v2.html#anmal` (Playwright or browser): form renders, stage select toggles decision fields, submit with backend running → success panel with `SC-` id; `curl -s http://localhost:8000/api/cases` contains the id.

- [ ] **Step 5: Commit** (with the other untracked site pages)

```bash
git add site/
git commit -m "feat(site): claim intake form wired to backend + legal and marketing pages"
```

---

### Task 4: OS dashboard — drop fake seeds, add inbound backend sync

**Files:**
- Modify: `os/app.js` (init at :152-169, delete `seedCases()` at :351-459, add 3 functions near `createCaseFromPayload`)
- Modify: `os/index.html` (sidebar-footer at :38-44)
- Modify: `os/api.js` (fix `osCaseToBackend` city mapping, delete unused `backendCaseToOs`)

- [ ] **Step 1: Replace `init()` seed block**

Old (app.js:152-169):
```js
  function init() {
    state = loadState();
    state.cases = state.cases.map(localizeCase);
    if (!state.cases.length) {
      state.cases = seedCases();
      state.selectedCaseId = state.cases[0].id;
      saveState();
    } else {
      saveState();
    }

    hydrateSelects();
    bindNavigation();
    bindIntake();
    bindImportExport();
    bindFilters();
    renderAll();
  }
```
New:
```js
  function init() {
    state = loadState();
    state.cases = state.cases.map(localizeCase);
    saveState();

    hydrateSelects();
    bindNavigation();
    bindIntake();
    bindImportExport();
    bindFilters();
    bindBackendSync();
    renderAll();
    syncFromBackend();
  }
```

- [ ] **Step 2: Delete the whole `seedCases()` function** (app.js:351-459, from `function seedCases() {` through its closing `}` — ends right before `function hydrateSelects`... verify the closing brace, the function ends with `});` then `}`)

- [ ] **Step 3: Add sync functions after `createCaseFromPayload`** (after app.js:659)

```js
  function bindBackendSync() {
    document.getElementById("syncBackendBtn").addEventListener("click", async () => {
      const added = await syncFromBackend();
      alert(added === null ? "Backend nås inte på localhost:8000." : `${added} nya ärenden hämtade.`);
    });
  }

  async function syncFromBackend() {
    if (!window.SwiftclaimAPI) return null;
    const backendCases = await window.SwiftclaimAPI.getCases();
    if (!backendCases) return null;
    let added = 0;
    backendCases.forEach((remote) => {
      if (state.cases.some((item) => item.id === remote.id)) return;
      const payload = backendCaseToPayload(remote);
      const newCase = createCaseFromPayload(payload, analyzeIntake(payload));
      newCase.id = remote.id;
      newCase.createdAt = remote.created_at || newCase.createdAt;
      newCase.timeline[0].body = "Ärende inskickat via Swiftclaim.se.";
      state.cases.unshift(newCase);
      added += 1;
    });
    if (added > 0) {
      saveState();
      renderAll();
    }
    return added;
  }

  function backendCaseToPayload(remote) {
    return {
      customerName: remote.customer_name || "",
      email: remote.customer_email || "",
      phone: remote.customer_phone || "",
      city: remote.property_address || "",
      propertyType: remote.property_type || "Villa",
      insuranceCompany: remote.insurance_company || companies[0],
      damageCategory: remote.damage_category || "Annan egendomsskada",
      incidentDate: remote.damage_date || "",
      decisionDate: "",
      claimedAmount: Number(remote.claim_amount) || 0,
      offeredAmount: Number(remote.insurer_amount) || 0,
      currentStage: remote.insurer_decision || "Ej inskickat",
      description: remote.damage_description || "",
      evidence: Array.isArray(remote.tags) ? remote.tags : [],
    };
  }
```

- [ ] **Step 4: Add sync button to sidebar footer** (os/index.html:38-44)

Old:
```html
        <div class="sidebar-footer">
          <button class="secondary full" id="exportJsonBtn" type="button">Exportera data</button>
```
New:
```html
        <div class="sidebar-footer">
          <button class="secondary full" id="syncBackendBtn" type="button">Synka från backend</button>
          <button class="secondary full" id="exportJsonBtn" type="button">Exportera data</button>
```

- [ ] **Step 5: api.js — fix city mapping, drop dead code**

In `osCaseToBackend`, replace `city: item.customer?.city || "",` with `property_address: item.customer?.city || "",`.
Delete the entire `backendCaseToOs` function (api.js:70-99) — replaced by `backendCaseToPayload` in app.js.

- [ ] **Step 6: Verify**

Open `http://localhost:8080/os/index.html` with backend running and ≥1 case in backend, after clearing storage (DevTools → `localStorage.removeItem("swiftclaim-os-state-v1")` or fresh profile):
- No fake cases (no "Alex Andersson").
- Submitted site case appears with scorecard, tasks, timeline "Ärende inskickat via Swiftclaim.se."
- "Synka från backend" button reports counts; backend stopped → reports unreachable.

- [ ] **Step 7: Commit**

```bash
git add os/
git commit -m "feat(os): pull real cases from backend, remove demo seed data"
```

---

### Task 5: End-to-end verification with a real case

**Files:** none (verification only)

- [ ] **Step 1: Full loop, fresh state**

Backend running (Task 1), ARN imported (Task 2), static server on 8080 (Task 3).
Submit via site form a realistic case, e.g.:
- Namn: real-ish name, Vattenskada, Länsförsäkringar, stage "Underbetalt"
- Beskrivning: "Vattenläcka från diskmaskinens anslutning i köket. Golv och underliggande konstruktion vattenskadades. Länsförsäkringar har godkänt golvbyte men nekar ersättning för avfuktning och köksskåp med hänvisning till åldersavdrag och bristande underhåll. Beslut mottaget [datum]. Yrkat 185 000 kr, erbjudet 64 000 kr."

- [ ] **Step 2: Confirm case in backend + OS**

`curl -s http://localhost:8000/api/cases | python3 -m json.tool | head -30` → case present.
OS at `http://localhost:8080/os/index.html` → case visible after sync.

- [ ] **Step 3: Generate real draft**

In OS case detail → Rättskunskap → "Generera juridiskt utkast" (or `curl -s -X POST http://localhost:8000/api/draft -H "Content-Type: application/json" -d '{"case_id": "<ID>"}'`).
Expected: draft text in Swedish citing FAL chapters/paragraphs and ARN case ids. Takes 30-90s.

- [ ] **Step 4: RAG sanity in OS Knowledge view**

Search "åldersavdrag vattenskada" → statute + precedent hits with scores.

No commit (nothing changed).

---

### Task 6: Repo hygiene — .gitignore + README

**Files:**
- Rewrite: `.gitignore`
- Rewrite: `README.md`

- [ ] **Step 1: Replace `.gitignore` entirely with:**

```gitignore
# OS / editor cruft
.DS_Store
Thumbs.db
desktop.ini
.vscode/
.idea/
*.swp
*~

# Node
node_modules/
npm-debug.log*
yarn-debug.log*
yarn-error.log*

# Python
__pycache__/
*.pyc
.venv/

# Local env / secrets
.env
.env.local
*.local

# Local tooling (kept out of repo)
.mcp.json
.playwright-mcp/
.scraper-inspect/

# Local databases (recreated by backend startup + /api/arn/import)
backend/data/*.db

# Law pipeline artifacts (regenerable or pre-anonymization PII — never publish)
law-pipeline/.embeddings.json
law-pipeline/raw_pdfs/
law-pipeline/processed/
```

- [ ] **Step 2: Rewrite `README.md`:**

```markdown
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
   │         LLM draft generation (OpenRouter → deepseek-chat)
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

Requirements: Python 3.11+, API keys in `backend/.env`
(`OPENROUTER_API_KEY`, `VOYAGE_API_KEY`).

```bash
# 1. Backend
cd backend && pip install -r requirements.txt && python run.py
# → http://localhost:8000 (docs at /docs)

# 2. Import ARN decisions from the vault
curl -X POST http://localhost:8000/api/arn/import -H "Content-Type: application/json" -d '{}'

# 3. Serve site + OS
python3 -m http.server 8080
# Site: http://localhost:8080/site/landing_v2.html
# OS:   http://localhost:8080/os/index.html
```

First RAG query builds the Voyage embeddings index over the vault
(`law-pipeline/.embeddings.json`, ~18 MB, not in git).

## Data provenance

- **Statutes** scraped from lagen.nu / riksdagen.se (public law).
- **ARN decisions** are public board decisions, LLM-anonymized before storage
  (GDPR caution). Raw PDFs and pre-anonymization text never enter git.

## Design

`site/DESIGN_GUIDELINES.md` is the design contract for all public pages.
```

- [ ] **Step 3: Commit**

```bash
git add .gitignore README.md
git commit -m "chore: publish vault + pipeline, ignore secrets and regenerable artifacts; rewrite README"
```

---

### Task 7: Commit remaining surfaces

**Files:** staging only

- [ ] **Step 1: Backend**

```bash
git add backend/
git commit -m "feat(backend): FastAPI claims API — CRUD, vault import, RAG search, LLM drafting"
```

- [ ] **Step 2: Vault + pipeline** (after .gitignore from Task 6 — verify excluded files stay out)

```bash
git add law-pipeline/ swiftclaim-obsidian/
git status --short | grep -E "raw_pdfs|processed|embeddings|\.env" && echo "STOP: leak" || echo "clean"
git commit -m "feat(data): legal knowledge vault (1,289 statutes + ARN) and ingestion pipeline"
```

- [ ] **Step 3: Agent context**

```bash
git add CLAUDE.md
git commit -m "docs: agent context for the Swiftclaim workspace"
```

---

### Task 8: Secret scan + push to GitHub

- [ ] **Step 1: Scan tracked content for key-shaped strings**

```bash
git grep -InE "(sk-or-v1-[A-Za-z0-9]+|sk-[A-Za-z0-9]{30,}|pa-[A-Za-z0-9_-]{30,}|OPENROUTER_API_KEY=.+|VOYAGE_API_KEY=.+)" HEAD -- . | grep -v "OPENROUTER_API_KEY=$" || echo "no secrets"
```
Expected: `no secrets` (README mentions key *names* only — names without values are fine; inspect any hit manually).

- [ ] **Step 2: Confirm no .env ever tracked**

Run: `git log --all --oneline --full-history -- "*.env" ".env"`
Expected: empty.

- [ ] **Step 3: Push**

```bash
git push origin main
```
Expected: all commits on `https://github.com/Leojustleo/swiftclaim`.

- [ ] **Step 4: Verify on GitHub**

`gh repo view Leojustleo/swiftclaim --web` or `gh api repos/Leojustleo/swiftclaim/contents | python3 -c "import json,sys; print([f['name'] for f in json.load(sys.stdin)])"`
Expected: `backend`, `site`, `os`, `law-pipeline`, `swiftclaim-obsidian`, `docs`, `README.md`, `CLAUDE.md`, `.gitignore`.
```
