# Automated Legal Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every new case automatically runs research → unified scorecard → appeal draft → review queue, with flexible knowledge ingestion (any new `.md` source becomes retrievable at any time) and outcome tracking for calibration.

**Architecture:** In-process extension of the existing FastAPI backend. A new `scorecard.py` replaces the unguarded `scoring.py` (all LLM traffic through the hardened `chat_json` chain). A new `pipeline.py` orchestrator (PipelineJob rows + BackgroundTasks, mirroring the DraftJob pattern) chains research → scoring → the existing draft-generation v2 → `needs_review`. `rag.py` gains vault-dir auto-discovery + an incremental reindex entry point.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy, SQLite, pytest (existing suite: `cd backend && python3 -m pytest tests/` — 45 passing before this plan). Vanilla JS admin dashboard.

**Spec:** `docs/superpowers/specs/2026-07-02-auto-legal-pipeline-design.md`

**Working directory for all backend commands:** `/Users/leo-mac/claude-code/Swiftclaim/backend`

## File map

| File | Action | Responsibility |
|---|---|---|
| `backend/app/scorecard.py` | Create | Unified scorecard: retrieval, one `chat_json` call, band/priority derivation, citation resolution, calibration helpers |
| `backend/app/scoring.py` | Delete | Replaced (unguarded direct-DeepSeek path) |
| `backend/app/pipeline.py` | Create | Orchestrator: PipelineJob stages research → scoring → drafting → done |
| `backend/app/intake_ai.py` | Modify | `assess` becomes thin wrapper over `build_scorecard`; store scorecard on Case |
| `backend/app/models.py` | Modify | `PipelineJob` model; `Case` outcome columns |
| `backend/app/db.py` | Modify | Migration for outcome columns |
| `backend/app/rag.py` | Modify | Dir auto-discovery, `reindex_vault()` |
| `backend/app/schemas.py` | Modify | `PipelineJobOut`, outcome fields on Case schemas |
| `backend/app/main.py` | Modify | Triggers, pipeline/reindex/outcome/review endpoints, calibration stats |
| `admin/index.html`, `admin/app.js` | Modify | Review-queue view |
| `backend/evals/run_scorecard_evals.py` | Create | Scorecard golden-set eval |
| `backend/tests/test_scorecard.py`, `test_pipeline.py` | Create | Unit tests |
| `backend/tests/test_scoring.py` | Delete | Tests of deleted module |
| `backend/tests/test_intake_ai.py`, `test_rag_helpers.py` | Modify | Updated/added tests |

---

### Task 1: Unified scorecard module

**Files:**
- Create: `backend/app/scorecard.py`
- Create: `backend/tests/test_scorecard.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_scorecard.py`:

```python
from app import scorecard

FIELDS = {
    "customer_name": "Anna Andersson",
    "customer_email": "anna@example.se",
    "customer_phone": "0701234567",
    "property_address": "Storgatan 1, Lund",
    "insurance_policy_number": "HF-99887766",
    "damage_category": "Vattenskada",
    "damage_description": "Läcka hos Anna Andersson, Storgatan 1, Lund",
    "insurance_company": "Folksam",
    "claim_amount": 180000,
    "insurer_decision": "partial",
    "insurer_amount": 72000,
    "insurer_reason": "Åldersavdrag enligt tabell",
}


def test_band_and_priority_derivation():
    assert scorecard.band_from_strength(85) == "stark"
    assert scorecard.band_from_strength(70) == "stark"
    assert scorecard.band_from_strength(69) == "medel"
    assert scorecard.band_from_strength(40) == "medel"
    assert scorecard.band_from_strength(39) == "svag"
    assert scorecard.band_from_strength(None) == "okänd"
    assert scorecard.priority_from_strength(70) == "high"
    assert scorecard.priority_from_strength(40) == "medium"
    assert scorecard.priority_from_strength(10) == "low"
    assert scorecard.priority_from_strength(None) == "unknown"


class FakeResolver:
    def resolve(self, ref):
        if "4 kap 6" in ref:
            return {"ref": "FAL 4 kap 6 §", "kind": "lagrum"}
        if "2020-08495" in ref:
            return {"ref": "ARN 2020-08495", "kind": "arn"}
        return None


def test_build_scorecard_scrubs_pii_and_flags_bad_refs(monkeypatch):
    captured = {}

    def fake_chat(system, user, schema, **kw):
        captured["user"] = user
        return schema(
            claim_strength=72, win_probability="65%", summary="Bra läge.",
            key_factors=["Åldersavdrag över villkorstabellen"],
            recommended_action="Bestrid med hänvisning till FAL.",
            missing_info=[],
            arn_references=["2020-08495", "1999-99999"],
            lagrum_references=["FAL 4 kap 6 §"],
        ), {"model": "m"}

    monkeypatch.setattr(scorecard, "chat_json", fake_chat)
    monkeypatch.setattr(scorecard, "build_resolver", lambda db, ev: FakeResolver())

    sc = scorecard.build_scorecard(None, FIELDS, law_hits=[], arn_hits=[])

    assert "Anna" not in captured["user"]
    assert "Storgatan" not in captured["user"]
    assert "[KUND]" in captured["user"]
    assert sc["claim_strength"] == 72
    assert sc["strength_band"] == "stark"
    assert sc["priority"] == "high"
    assert sc["arn_references"] == ["ARN 2020-08495"]
    assert sc["lagrum_references"] == ["FAL 4 kap 6 §"]
    assert sc["flagged_references"] == ["1999-99999"]
    assert sc["degraded"] is False


def test_build_scorecard_degrades_on_llm_failure(monkeypatch):
    def boom(*a, **kw):
        raise scorecard.LLMError("down")

    monkeypatch.setattr(scorecard, "chat_json", boom)
    sc = scorecard.build_scorecard(None, FIELDS, law_hits=[], arn_hits=[])
    assert sc["degraded"] is True
    assert sc["claim_strength"] is None
    assert sc["strength_band"] == "okänd"
    assert sc["priority"] == "unknown"


def test_build_scorecard_flags_all_refs_when_resolver_unavailable(monkeypatch):
    def fake_chat(system, user, schema, **kw):
        return schema(
            claim_strength=50, win_probability="50%", summary="s",
            key_factors=[], recommended_action="", missing_info=[],
            arn_references=["2020-08495"], lagrum_references=["FAL 4 kap 6 §"],
        ), {"model": "m"}

    def broken_resolver(db, ev):
        raise RuntimeError("no index")

    monkeypatch.setattr(scorecard, "chat_json", fake_chat)
    monkeypatch.setattr(scorecard, "build_resolver", broken_resolver)
    sc = scorecard.build_scorecard(None, FIELDS, law_hits=[], arn_hits=[])
    assert sc["arn_references"] == []
    assert sc["lagrum_references"] == []
    assert set(sc["flagged_references"]) == {"2020-08495", "FAL 4 kap 6 §"}


def test_parse_probability():
    assert scorecard.parse_probability("65%") == 65
    assert scorecard.parse_probability("ca 70 procent") == 70
    assert scorecard.parse_probability(None) is None
    assert scorecard.parse_probability("") is None


def test_calibration_buckets():
    rows = [
        ("65%", "won"), ("70%", "lost"), ("30%", "lost"),
        ("90%", "partial"), (None, "won"), ("50%", "withdrawn"),
    ]
    out = scorecard.calibration_buckets(rows)
    assert out["60-79"] == {"n": 2, "wins": 1}
    assert out["0-39"] == {"n": 1, "wins": 0}
    assert out["80-100"] == {"n": 1, "wins": 1}
    assert out["40-59"] == {"n": 0, "wins": 0}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_scorecard.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.scorecard'`.

- [ ] **Step 3: Implement `backend/app/scorecard.py`**

```python
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.llm import LLMError, chat_json, scrub_pii
from app.rag import search_law, search_precedents
from app.verify import build_resolver


class ScorecardOut(BaseModel):
    claim_strength: int
    win_probability: str
    summary: str = ""
    key_factors: List[str] = []
    recommended_action: str = ""
    missing_info: List[str] = []
    arn_references: List[str] = []
    lagrum_references: List[str] = []


SCORECARD_SYSTEM = (
    "Du är en svensk försäkringsjurist på Swiftclaim. Bedöm ärendet mot lagrum "
    "och ARN-praxis nedan. Var saklig, lova aldrig ett utfall, och hänvisa bara "
    "till lagrum och ARN-beslut som citeras i underlaget.\n\n"
    "Svara endast med JSON:\n"
    "{\n"
    '  "claim_strength": <heltal 0-100>,\n'
    '  "win_probability": "<procent som sträng, t.ex. \'65%\'>",\n'
    '  "summary": "<2-4 meningar på svenska riktade till kunden: vad vi ser i ärendet>",\n'
    '  "key_factors": ["<faktor>", ...],\n'
    '  "recommended_action": "<max 2 meningar, hänvisa till ARN-beslut om möjligt>",\n'
    '  "missing_info": ["<uppgift eller dokument som saknas>", ...],\n'
    '  "arn_references": ["<ARN-nummer, t.ex. 2020-08495>", ...],\n'
    '  "lagrum_references": ["<t.ex. FAL 4 kap 6 §>", ...]\n'
    "}"
)


def band_from_strength(strength: Optional[int]) -> str:
    if strength is None:
        return "okänd"
    if strength >= 70:
        return "stark"
    if strength >= 40:
        return "medel"
    return "svag"


def priority_from_strength(strength: Optional[int]) -> str:
    if strength is None:
        return "unknown"
    if strength >= 70:
        return "high"
    if strength >= 40:
        return "medium"
    return "low"


def retrieve_evidence(fields: Dict[str, Any]) -> Tuple[List[Dict], List[Dict], bool]:
    category = fields.get("damage_category") or ""
    safe_desc = scrub_pii(fields.get("damage_description") or "", fields)
    query = f"{category} {safe_desc[:300]}"
    reason = fields.get("insurer_reason") or ""
    if reason:
        query += f" {scrub_pii(reason, fields)[:200]}"
    try:
        law_hits = [h for h in search_law(query, k=8) if h["path"].startswith("Lagstiftning/")][:5]
        arn_hits = search_precedents(category, scrub_pii(reason or safe_desc, fields), k=5)
        return law_hits, arn_hits, False
    except Exception:
        return [], [], True


def _case_block(fields: Dict[str, Any]) -> str:
    return "\n".join([
        "ÄRENDE:",
        f"Kategori: {fields.get('damage_category') or '—'}",
        f"Försäkringsbolag: {fields.get('insurance_company') or 'okänt'}",
        f"Yrkat belopp: {fields.get('claim_amount') or 'ej angivet'}",
        f"Erbjudet belopp: {fields.get('insurer_amount') or 'ej angivet'}",
        f"Bolagets beslut: {fields.get('insurer_decision') or 'inget ännu'}",
        f"Bolagets motivering: {fields.get('insurer_reason') or 'ingen'}",
        f"Beskrivning: {(fields.get('damage_description') or '')[:1500]}",
    ])


def _resolve_references(db, arn_references: List[str],
                        lagrum_references: List[str]) -> Tuple[List[str], List[str], List[str]]:
    try:
        resolver = build_resolver(db, set())
    except Exception:
        return [], [], [str(r) for r in list(arn_references) + list(lagrum_references)]
    arn_refs: List[str] = []
    lagrum_refs: List[str] = []
    flagged: List[str] = []
    for ref in arn_references:
        hit = resolver.resolve(str(ref))
        (arn_refs.append(hit["ref"]) if hit else flagged.append(str(ref)))
    for ref in lagrum_references:
        hit = resolver.resolve(str(ref))
        (lagrum_refs.append(hit["ref"]) if hit else flagged.append(str(ref)))
    return arn_refs, lagrum_refs, flagged


def degraded_scorecard(rag_failed: bool = False) -> Dict[str, Any]:
    return {
        "claim_strength": None,
        "strength_band": "okänd",
        "win_probability": None,
        "priority": "unknown",
        "summary": "Vi har tagit emot ditt ärende. En handläggare går igenom det och återkommer.",
        "key_factors": [],
        "recommended_action": "",
        "missing_info": [],
        "arn_references": [],
        "lagrum_references": [],
        "flagged_references": [],
        "degraded": True,
        "generated_at": datetime.utcnow().isoformat(),
    }


def build_scorecard(db: Optional[Session], fields: Dict[str, Any],
                    law_hits: Optional[List[Dict]] = None,
                    arn_hits: Optional[List[Dict]] = None,
                    job_id: Optional[str] = None) -> Dict[str, Any]:
    if law_hits is None or arn_hits is None:
        law_hits, arn_hits, rag_failed = retrieve_evidence(fields)
    else:
        rag_failed = False

    parts = [_case_block(fields), "\nRELEVANTA LAGRUM:"]
    for h in law_hits:
        parts.append(f"** {h['title']} **\n{h['text'][:800]}")
    parts.append("\nRELEVANTA ARN-BESLUT:")
    for h in arn_hits:
        parts.append(f"** {h['title']} **\n{h['text'][:800]}")

    try:
        out, _ = chat_json(SCORECARD_SYSTEM, scrub_pii("\n\n".join(parts), fields),
                           ScorecardOut, db=db, job_id=job_id,
                           stage="scorecard", max_tokens=1500)
    except LLMError:
        return degraded_scorecard(rag_failed)

    strength = max(0, min(100, int(out.claim_strength)))
    arn_refs, lagrum_refs, flagged = _resolve_references(db, out.arn_references, out.lagrum_references)
    return {
        "claim_strength": strength,
        "strength_band": band_from_strength(strength),
        "win_probability": out.win_probability,
        "priority": priority_from_strength(strength),
        "summary": out.summary[:1200],
        "key_factors": [str(f) for f in out.key_factors][:6],
        "recommended_action": out.recommended_action[:500],
        "missing_info": [str(m) for m in out.missing_info][:6],
        "arn_references": arn_refs,
        "lagrum_references": lagrum_refs,
        "flagged_references": flagged,
        "degraded": rag_failed,
        "generated_at": datetime.utcnow().isoformat(),
    }


def parse_probability(value: Any) -> Optional[int]:
    digits = re.sub(r"[^0-9]", "", str(value or ""))
    if not digits:
        return None
    return max(0, min(100, int(digits[:3])))


CALIBRATION_BUCKETS = [(0, 39, "0-39"), (40, 59, "40-59"), (60, 79, "60-79"), (80, 100, "80-100")]


def calibration_buckets(rows: List[Tuple[Any, Optional[str]]]) -> Dict[str, Dict[str, int]]:
    out = {label: {"n": 0, "wins": 0} for _, _, label in CALIBRATION_BUCKETS}
    for prob, outcome in rows:
        p = parse_probability(prob)
        if p is None or outcome not in ("won", "partial", "lost"):
            continue
        for lo, hi, label in CALIBRATION_BUCKETS:
            if lo <= p <= hi:
                out[label]["n"] += 1
                if outcome in ("won", "partial"):
                    out[label]["wins"] += 1
                break
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_scorecard.py -v`
Expected: all 6 PASS. Then `python3 -m pytest tests/ -v` — everything still passes.

- [ ] **Step 5: Commit**

```bash
git add tests/test_scorecard.py app/scorecard.py
git commit -m "feat: unified scorecard module on hardened LLM chain with citation resolution"
```

---

### Task 2: Migrate callers, delete scoring.py

**Files:**
- Modify: `backend/app/intake_ai.py`
- Modify: `backend/app/main.py:232-255` (admin score endpoint)
- Delete: `backend/app/scoring.py`, `backend/tests/test_scoring.py`
- Modify: `backend/tests/test_intake_ai.py`

- [ ] **Step 1: Update the intake tests**

In `backend/tests/test_intake_ai.py`, DELETE `test_assess_scrubs_pii` (scrubbing now happens inside `build_scorecard`, covered by `test_scorecard.py`) and ADD:

```python
def test_assess_maps_unified_scorecard(monkeypatch):
    sc = {"strength_band": "stark", "summary": "ok", "key_factors": ["a"],
          "missing_info": ["b"], "degraded": False, "claim_strength": 80}
    monkeypatch.setattr(intake_ai, "build_scorecard", lambda db, f, **kw: sc)
    out = intake_ai.assess(FIELDS, law_hits=[], arn_hits=[])
    assert out["strength"] == "stark"
    assert out["key_arguments"] == ["a"]
    assert out["missing_info"] == ["b"]
    assert out["scorecard"] is sc
    assert out["degraded"] is False
```

`test_categorize_scrubs_pii` and `test_new_case_id_falls_back_when_pool_exhausted` stay unchanged.

- [ ] **Step 2: Run tests to verify the new one fails**

Run: `python3 -m pytest tests/test_intake_ai.py -v`
Expected: `test_assess_maps_unified_scorecard` FAILS with `AttributeError: <module 'app.intake_ai'> has no attribute 'build_scorecard'`.

- [ ] **Step 3: Rewrite `intake_ai.assess` as a thin wrapper**

In `backend/app/intake_ai.py`:

Replace the imports of rag with scorecard (delete `from app.rag import search_law, search_precedents`; the `AssessOut` class and `ASSESS_SYSTEM` constant are deleted too):

```python
from app.llm import LLMError, chat_json, scrub_pii
from app.models import Case
from app.scorecard import build_scorecard, retrieve_evidence
```

Replace the entire `assess` function with:

```python
def assess(fields: Dict[str, Any], law_hits: List[Dict], arn_hits: List[Dict],
           db: Session = None) -> Dict[str, Any]:
    sc = build_scorecard(db, fields, law_hits=law_hits, arn_hits=arn_hits)
    return {
        "strength": sc["strength_band"],
        "summary": sc["summary"],
        "key_arguments": sc["key_factors"][:6],
        "missing_info": sc["missing_info"][:6],
        "degraded": sc["degraded"],
        "scorecard": sc,
    }
```

In `analyze`, replace the retrieval block (the `rag_query = ...` through the `except Exception:` block) with:

```python
    law_hits, arn_hits, rag_failed = retrieve_evidence(dict(payload, damage_category=category))
```

(the `safe_description` variable and `rag_query` lines are no longer needed; delete them), and store the scorecard on the case — add `import json` at the top of the file, then just before the `case = Case(` constructor:

```python
    sc = assessment.get("scorecard")
```

and add to the `Case(` constructor kwargs:

```python
        scorecard=json.dumps(sc, ensure_ascii=False) if sc else None,
```

- [ ] **Step 4: Rewire the admin score endpoint and delete scoring.py**

In `backend/app/main.py`, add to the imports (top of file):

```python
from app.scorecard import build_scorecard, calibration_buckets
from app.draft_ai import case_fields
```

(merge with the existing `from app.draft_ai import create_job, run_draft_job, fail_if_stale` line: `from app.draft_ai import create_job, run_draft_job, fail_if_stale, case_fields`.)

Replace the body of `admin_score_case`:

```python
@app.post("/api/admin/cases/{case_id}/score")
def admin_score_case(
    case_id: str,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin_token),
):
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    scorecard = build_scorecard(db, case_fields(case))
    case.scorecard = _json.dumps(scorecard, ensure_ascii=False)
    db.commit()
    return scorecard
```

Then delete the old module and its tests:

```bash
git rm app/scoring.py tests/test_scoring.py
```

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest tests/ -v`
Expected: all PASS (old scoring tests gone, new intake test green). Also verify nothing still imports the dead module: `grep -rn "app.scoring\|from app import scoring" app/ tests/ evals/` → no hits.

- [ ] **Step 6: Commit**

```bash
git add -A app/ tests/
git commit -m "refactor: intake and admin scoring unified on scorecard module, drop scoring.py"
```

---

### Task 3: PipelineJob model + orchestrator

**Files:**
- Modify: `backend/app/models.py` (add PipelineJob)
- Create: `backend/app/pipeline.py`
- Create: `backend/tests/test_pipeline.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_pipeline.py`:

```python
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app import pipeline
from app.models import Case, DraftJob


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _case(db, **kw):
    c = Case(id="SC-2607-123", customer_name="A", insurance_company="If",
             damage_category="Vattenskada", damage_description="läcka", **kw)
    db.add(c)
    db.commit()
    return c


def _fake_draft(db, monkeypatch, final_status="done", error=None):
    def fake_create_job(d, case_id, strategy, ctx):
        dj = DraftJob(id="dj-1", case_id=case_id, status="queued")
        d.add(dj)
        d.commit()
        return dj

    def fake_run_draft_job(job_id):
        dj = db.query(DraftJob).filter(DraftJob.id == job_id).first()
        dj.status, dj.error = final_status, error
        db.commit()

    monkeypatch.setattr(pipeline, "create_job", fake_create_job)
    monkeypatch.setattr(pipeline, "run_draft_job", fake_run_draft_job)


def test_happy_path_lands_in_review_queue(db, monkeypatch):
    case = _case(db)
    job = pipeline.create_pipeline_job(db, case.id)
    monkeypatch.setattr(pipeline, "retrieve_evidence", lambda f: ([], [], False))
    monkeypatch.setattr(pipeline, "build_scorecard",
                        lambda d, f, **kw: {"claim_strength": 80, "priority": "high", "degraded": False})
    _fake_draft(db, monkeypatch)

    pipeline._run_stages(db, job, case)

    assert job.status == "done"
    assert case.status == "needs_review"
    assert json.loads(case.scorecard)["claim_strength"] == 80
    assert job.stages["draft"]["status"] == "done"


def test_scorecard_crash_still_reaches_queue(db, monkeypatch):
    case = _case(db)
    job = pipeline.create_pipeline_job(db, case.id)
    monkeypatch.setattr(pipeline, "retrieve_evidence", lambda f: ([], [], False))

    def boom(*a, **kw):
        raise RuntimeError("scoring exploded")

    monkeypatch.setattr(pipeline, "build_scorecard", boom)
    _fake_draft(db, monkeypatch)

    pipeline._run_stages(db, job, case)

    assert job.status == "done"
    assert case.status == "needs_review"
    sc = json.loads(case.scorecard)
    assert sc["degraded"] is True
    assert "scoring exploded" in sc["error"]


def test_draft_crash_still_reaches_queue_with_scorecard(db, monkeypatch):
    case = _case(db)
    job = pipeline.create_pipeline_job(db, case.id)
    monkeypatch.setattr(pipeline, "retrieve_evidence", lambda f: ([], [], False))
    monkeypatch.setattr(pipeline, "build_scorecard",
                        lambda d, f, **kw: {"claim_strength": 55, "priority": "medium", "degraded": False})

    def boom(*a, **kw):
        raise RuntimeError("draft exploded")

    monkeypatch.setattr(pipeline, "create_job", boom)

    pipeline._run_stages(db, job, case)

    assert job.status == "done"
    assert case.status == "needs_review"
    assert json.loads(case.scorecard)["claim_strength"] == 55
    assert job.stages["draft"]["status"] == "failed"
    assert "draft exploded" in job.stages["draft"]["error"]


def test_already_scored_case_skips_research_and_scoring(db, monkeypatch):
    case = _case(db, scorecard='{"claim_strength": 90, "priority": "high"}')
    job = pipeline.create_pipeline_job(db, case.id)

    def boom(*a, **kw):
        raise AssertionError("should not run")

    monkeypatch.setattr(pipeline, "retrieve_evidence", boom)
    monkeypatch.setattr(pipeline, "build_scorecard", boom)
    _fake_draft(db, monkeypatch)

    pipeline._run_stages(db, job, case)

    assert job.status == "done"
    assert case.status == "needs_review"
    assert job.stages["scorecard"]["skipped"] == "case already scored"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_pipeline.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.pipeline'`.

- [ ] **Step 3: Add the PipelineJob model**

In `backend/app/models.py`, add after the `DraftJob` class:

```python
class PipelineJob(Base):
    __tablename__ = "pipeline_jobs"

    id = Column(String, primary_key=True)
    case_id = Column(String, ForeignKey("cases.id"), index=True)
    status = Column(String, default="queued")  # queued, research, scoring, drafting, done, failed
    stages = Column(JSON, default={})
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
```

(New table — `Base.metadata.create_all` picks it up; no migration needed.)

- [ ] **Step 4: Implement `backend/app/pipeline.py`**

```python
import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.draft_ai import case_fields, create_job, run_draft_job
from app.models import Case, DraftJob, PipelineJob
from app.scorecard import build_scorecard, degraded_scorecard, retrieve_evidence


def create_pipeline_job(db: Session, case_id: str) -> PipelineJob:
    job = PipelineJob(id=f"pl-{uuid.uuid4().hex[:12]}", case_id=case_id, status="queued", stages={})
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _set_stage(db: Session, job: PipelineJob, status: str, key: str, snapshot: Any) -> None:
    job.status = status
    stages = dict(job.stages or {})
    stages[key] = snapshot
    job.stages = stages
    job.updated_at = datetime.utcnow()
    db.commit()


def run_pipeline(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.query(PipelineJob).filter(PipelineJob.id == job_id).first()
        if not job:
            return
        case = db.query(Case).filter(Case.id == job.case_id).first()
        if not case:
            job.status, job.error = "failed", "case not found"
            db.commit()
            return
        try:
            _run_stages(db, job, case)
        except Exception as e:
            job.status, job.error = "failed", f"{type(e).__name__}: {e}"
            db.commit()
    finally:
        db.close()


def _run_stages(db: Session, job: PipelineJob, case: Case) -> None:
    fields = case_fields(case)

    if case.scorecard:
        _set_stage(db, job, "scoring", "scorecard", {"skipped": "case already scored"})
    else:
        job.status = "research"
        db.commit()
        law_hits, arn_hits, rag_failed = retrieve_evidence(fields)
        _set_stage(db, job, "research", "research", {
            "law_hits": [h["title"] for h in law_hits],
            "arn_hits": [h["title"] for h in arn_hits],
            "failed": rag_failed,
        })

        job.status = "scoring"
        db.commit()
        try:
            sc = build_scorecard(db, fields, law_hits=law_hits, arn_hits=arn_hits, job_id=job.id)
        except Exception as e:
            sc = degraded_scorecard(True)
            sc["error"] = f"{type(e).__name__}: {e}"
        case.scorecard = json.dumps(sc, ensure_ascii=False)
        _set_stage(db, job, "scoring", "scorecard", {
            "degraded": sc["degraded"],
            "claim_strength": sc["claim_strength"],
            "priority": sc["priority"],
        })

    job.status = "drafting"
    db.commit()
    try:
        draft_job = create_job(db, case.id, "maximize_payout", "")
        run_draft_job(draft_job.id)
        db.expire_all()
        dj = db.query(DraftJob).filter(DraftJob.id == draft_job.id).first()
        _set_stage(db, job, "drafting", "draft", {
            "draft_job_id": draft_job.id,
            "status": dj.status if dj else "missing",
            "error": dj.error if dj else None,
        })
    except Exception as e:
        _set_stage(db, job, "drafting", "draft",
                   {"status": "failed", "error": f"{type(e).__name__}: {e}"})

    case.status = "needs_review"
    job.status = "done"
    job.updated_at = datetime.utcnow()
    db.commit()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_pipeline.py tests/ -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add app/models.py app/pipeline.py tests/test_pipeline.py
git commit -m "feat: pipeline orchestrator — research → scoring → draft → review queue"
```

---

### Task 4: Wire triggers + pipeline endpoints

**Files:**
- Modify: `backend/app/main.py` (create_case, analyze_intake, startup, new endpoints)
- Modify: `backend/app/schemas.py` (PipelineJobOut)

No new unit tests (endpoint glue; the suite convention is pure functions only). Verified live in Final Verification.

- [ ] **Step 1: Add `PipelineJobOut` to `backend/app/schemas.py`** (after `DraftJobOut`):

```python
class PipelineJobOut(BaseModel):
    id: str
    case_id: str
    status: str
    error: Optional[str] = None
    stages: dict = {}
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
```

- [ ] **Step 2: Wire `backend/app/main.py`**

Imports — extend the models import and add pipeline + schema:

```python
from app.models import Case, ARNDecision, LawSection as LawSectionModel, ResponseDraft, KnowledgeNote, DraftJob, PipelineJob
from app.pipeline import create_pipeline_job, run_pipeline
```

and add `PipelineJobOut` to the `from app.schemas import (...)` list.

In `startup()`, extend the stuck-job cleanup (after the DraftJob block, before `db.commit()`):

```python
        stuck_pl = db.query(PipelineJob).filter(PipelineJob.status.notin_(["done", "failed"]))
        stuck_pl.update({"status": "failed", "error": "server restarted"}, synchronize_session=False)
```

Replace `create_case` (trigger only on truly-new cases):

```python
@app.post("/api/cases", response_model=CaseOut, status_code=201)
def create_case(data: CaseCreate, background: BackgroundTasks, db: Session = Depends(get_db)):
    case = db.query(Case).filter(Case.id == data.id).first()
    is_new = case is None
    if case:
        for key, val in data.model_dump().items():
            if key != "id":
                setattr(case, key, val)
        case.updated_at = datetime.utcnow()
    else:
        case = Case(**data.model_dump())
        db.add(case)
    db.commit()
    db.refresh(case)
    if is_new:
        pj = create_pipeline_job(db, case.id)
        background.add_task(run_pipeline, pj.id)
    return CaseOut.model_validate(case)
```

Replace `analyze_intake`:

```python
@app.post("/api/intake/analyze", response_model=IntakeAnalysisOut)
def analyze_intake(req: IntakeAnalyzeRequest, background: BackgroundTasks, db: Session = Depends(get_db)):
    result = run_intake_analysis(req.model_dump(), db)
    pj = create_pipeline_job(db, result["case_id"])
    background.add_task(run_pipeline, pj.id)
    return result
```

Add pipeline-job endpoints (after the draft-job endpoints; `fail_if_stale` is duck-typed and works on PipelineJob rows):

```python
@app.get("/api/pipeline-jobs/{job_id}", response_model=PipelineJobOut)
def get_pipeline_job(job_id: str, db: Session = Depends(get_db)):
    job = db.query(PipelineJob).filter(PipelineJob.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    return PipelineJobOut.model_validate(fail_if_stale(db, job))


@app.get("/api/pipeline-jobs", response_model=Optional[PipelineJobOut])
def get_latest_pipeline_job(case_id: str, db: Session = Depends(get_db)):
    job = db.query(PipelineJob).filter(PipelineJob.case_id == case_id) \
        .order_by(PipelineJob.created_at.desc()).first()
    return PipelineJobOut.model_validate(fail_if_stale(db, job)) if job else None
```

- [ ] **Step 3: Verify the app imports and the suite passes**

Run: `python3 -c "from app.main import app; print('ok')" && python3 -m pytest tests/ -v`
Expected: `ok`, all tests PASS.

- [ ] **Step 4: Commit**

```bash
git add app/main.py app/schemas.py
git commit -m "feat: auto-trigger pipeline on case creation, pipeline-job endpoints"
```

---

### Task 5: Flexible ingestion — vault dir auto-discovery + reindex

**Files:**
- Modify: `backend/app/rag.py` (eligible_notes, reindex_vault)
- Modify: `backend/tests/test_rag_helpers.py`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_rag_helpers.py` (add imports at top if missing: `from app import rag`):

```python
def test_eligible_notes_includes_new_top_level_dir():
    notes = [
        {"path": "Domar/NJA 2020 s 1.md", "title": "NJA 2020 s 1", "text": "x" * 100},
        {"path": "Index/allt.md", "title": "allt", "text": "x" * 100},
        {"path": "rot.md", "title": "rot", "text": "x" * 100},
    ]
    got = rag.eligible_notes(notes)
    assert [n["path"] for n in got] == ["Domar/NJA 2020 s 1.md"]


def test_eligible_notes_alias_and_literal_dirs():
    notes = [
        {"path": "ARN/ARN 2020-1.md", "title": "ARN 2020-1", "text": "x" * 100},
        {"path": "Domar/dom.md", "title": "dom", "text": "x" * 100},
    ]
    assert [n["path"] for n in rag.eligible_notes(notes, dirs=["arn"])] == ["ARN/ARN 2020-1.md"]
    assert [n["path"] for n in rag.eligible_notes(notes, dirs=["Domar"])] == ["Domar/dom.md"]


def test_reindex_vault_embeds_only_new_files(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    (vault / "Domar").mkdir(parents=True)
    (vault / "Domar" / "a.md").write_text("innehåll om vattenskada och åldersavdrag " * 4)
    monkeypatch.setattr(rag, "EMBED_CACHE", tmp_path / "emb.json")
    monkeypatch.setattr(rag, "voyage_embed",
                        lambda texts, key, input_type, **kw: [[0.1] * 4 for _ in texts])
    monkeypatch.setattr(rag, "_get_voyage_key", lambda: "k")

    assert rag.reindex_vault(vault) == {"total_notes": 1, "embedded": 1}
    assert rag.reindex_vault(vault) == {"total_notes": 1, "embedded": 0}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_rag_helpers.py -v`
Expected: the first two FAIL on the current DIR_MAP behavior (`Domar/` filtered out; `dirs=["Domar"]` raises `KeyError`), the third FAILS with `AttributeError: ... no attribute 'reindex_vault'`.

- [ ] **Step 3: Implement in `backend/app/rag.py`**

Below `DIR_MAP`, add:

```python
EXCLUDED_TOP_DIRS = {"Index"}
```

Replace `eligible_notes`:

```python
def dir_prefixes(notes: List[NoteDict], dirs: Optional[List[str]] = None) -> Tuple[str, ...]:
    """Alias (DIR_MAP key) or literal top-level vault dir → path prefix.
    No dirs given → every discovered top-level dir except EXCLUDED_TOP_DIRS."""
    if dirs:
        return tuple(DIR_MAP.get(d, f"{d.rstrip('/')}/") for d in dirs)
    tops = {n["path"].split("/", 1)[0] for n in notes if "/" in n["path"]}
    return tuple(f"{t}/" for t in sorted(tops) if t not in EXCLUDED_TOP_DIRS)


def eligible_notes(notes: List[NoteDict], dirs: Optional[List[str]] = None) -> List[NoteDict]:
    prefixes = dir_prefixes(notes, dirs)
    if not prefixes:
        return []
    return [n for n in notes if n["path"].startswith(prefixes) and len(n["text"]) <= MAX_NOTE_CHARS]
```

Add `reindex_vault` (after `get_index`):

```python
def reindex_vault(vault_path: Optional[Path] = None) -> Dict[str, Any]:
    """Incremental reindex: embed only new/changed vault files, then force
    the singleton index to reload. Safe to call any time new data lands."""
    notes = load_vault_notes(vault_path)
    cache: Dict[str, Any] = {}
    if EMBED_CACHE.exists():
        cache = json.loads(EMBED_CACHE.read_text())
    stale = [n for n in notes
             if (cache.get(n["path"]) or {}).get("hash") != _content_hash(n["text"])]
    build_or_load_index(notes)
    _INDEX["notes"] = None
    return {"total_notes": len(notes), "embedded": len(stale)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/ -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add app/rag.py tests/test_rag_helpers.py
git commit -m "feat: vault dir auto-discovery + incremental reindex_vault — new data anytime"
```

---

### Task 6: Reindex endpoints

**Files:**
- Modify: `backend/app/main.py`

- [ ] **Step 1: Add the endpoints** (near the other admin endpoints in `main.py`):

```python
_REINDEX: dict = {"status": "idle", "started_at": None, "finished_at": None,
                  "total_notes": 0, "embedded": 0, "error": None}


def _do_reindex():
    from app.rag import reindex_vault
    try:
        stats = reindex_vault()
        _REINDEX.update(status="done", finished_at=datetime.utcnow().isoformat(),
                        error=None, **stats)
    except Exception as e:
        _REINDEX.update(status="failed", finished_at=datetime.utcnow().isoformat(),
                        error=f"{type(e).__name__}: {e}")


@app.post("/api/reindex", status_code=202)
def start_reindex(background: BackgroundTasks, _: dict = Depends(require_admin_token)):
    if _REINDEX["status"] == "running":
        raise HTTPException(409, "Reindex already running")
    _REINDEX.update(status="running", started_at=datetime.utcnow().isoformat(),
                    finished_at=None, error=None)
    background.add_task(_do_reindex)
    return {"status": "running"}


@app.get("/api/reindex/status")
def reindex_status(_: dict = Depends(require_admin_token)):
    return _REINDEX
```

- [ ] **Step 2: Verify import + suite**

Run: `python3 -c "from app.main import app; print('ok')" && python3 -m pytest tests/ -q`
Expected: `ok`, all PASS.

- [ ] **Step 3: Commit**

```bash
git add app/main.py
git commit -m "feat: admin reindex endpoints for on-demand knowledge ingestion"
```

---

### Task 7: Outcome tracking + calibration stats

**Files:**
- Modify: `backend/app/models.py` (Case columns)
- Modify: `backend/app/db.py` (migration)
- Modify: `backend/app/schemas.py` (CaseUpdate, CaseOut)
- Modify: `backend/app/main.py` (outcome endpoint, admin dict, stats)

(The pure calibration logic was tested in Task 1; this task is wiring.)

- [ ] **Step 1: Add Case columns** in `backend/app/models.py` (after `outcome = Column(String, nullable=True)`):

```python
    actual_outcome = Column(String, nullable=True)  # won, partial, lost, withdrawn
    actual_amount_sek = Column(Integer, nullable=True)
    outcome_date = Column(String, nullable=True)
```

- [ ] **Step 2: Migrate** — in `backend/app/db.py` `_migrate`, extend the cases block:

```python
        if "actual_outcome" not in cols:
            conn.execute(text("ALTER TABLE cases ADD COLUMN actual_outcome VARCHAR"))
        if "actual_amount_sek" not in cols:
            conn.execute(text("ALTER TABLE cases ADD COLUMN actual_amount_sek INTEGER"))
        if "outcome_date" not in cols:
            conn.execute(text("ALTER TABLE cases ADD COLUMN outcome_date VARCHAR"))
```

(add before the first `conn.commit()`).

- [ ] **Step 3: Schemas** — in `backend/app/schemas.py` add to BOTH `CaseUpdate` and `CaseOut`:

```python
    actual_outcome: Optional[str] = None
    actual_amount_sek: Optional[int] = None
    outcome_date: Optional[str] = None
```

- [ ] **Step 4: main.py wiring**

Add to `_case_to_admin_dict`'s returned dict:

```python
        "actual_outcome": case.actual_outcome,
        "actual_amount_sek": case.actual_amount_sek,
        "outcome_date": case.outcome_date,
```

Add the outcome endpoint (near the other admin endpoints):

```python
class _OutcomeRequest(_BaseModel):
    actual_outcome: str
    actual_amount_sek: Optional[int] = None
    outcome_date: Optional[str] = None


@app.post("/api/admin/cases/{case_id}/outcome")
def admin_set_outcome(
    case_id: str,
    body: _OutcomeRequest,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin_token),
):
    if body.actual_outcome not in ("won", "partial", "lost", "withdrawn"):
        raise HTTPException(422, "actual_outcome must be won|partial|lost|withdrawn")
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")
    case.actual_outcome = body.actual_outcome
    case.actual_amount_sek = body.actual_amount_sek
    case.outcome_date = body.outcome_date
    db.commit()
    sc = _json.loads(case.scorecard) if case.scorecard else None
    return _case_to_admin_dict(case, sc)
```

In `admin_stats`, before the `return`, add:

```python
    calib_rows = []
    for c in cases:
        if c.scorecard:
            sc = _json.loads(c.scorecard)
            calib_rows.append((sc.get("win_probability"), c.actual_outcome))
```

and add to the returned dict:

```python
        "calibration": calibration_buckets(calib_rows),
```

- [ ] **Step 5: Verify + commit**

Run: `python3 -c "from app.main import app; print('ok')" && python3 -m pytest tests/ -q`
Expected: `ok`, all PASS.

```bash
git add app/models.py app/db.py app/schemas.py app/main.py
git commit -m "feat: outcome tracking on cases + win-probability calibration in admin stats"
```

---

### Task 8: Review queue — API + admin UI

**Files:**
- Modify: `backend/app/main.py` (review endpoint, richer admin_get_case)
- Modify: `admin/index.html`, `admin/app.js`

- [ ] **Step 1: Review endpoint + richer case detail** in `backend/app/main.py`:

```python
class _ReviewRequest(_BaseModel):
    action: str  # approve | reject


@app.post("/api/admin/cases/{case_id}/review")
def admin_review_case(
    case_id: str,
    body: _ReviewRequest,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin_token),
):
    if body.action not in ("approve", "reject"):
        raise HTTPException(422, "action must be approve|reject")
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")
    latest = db.query(ResponseDraft).filter(ResponseDraft.case_id == case_id) \
        .order_by(ResponseDraft.version.desc()).first()
    if body.action == "approve":
        case.status = "approved"
        if latest:
            latest.status = "reviewed"
    else:
        case.status = "analysis"
        if latest:
            latest.status = "archived"
    db.commit()
    return {"ok": True, "status": case.status}
```

Replace `admin_get_case` so the review view gets draft + pipeline info:

```python
@app.get("/api/admin/cases/{case_id}")
def admin_get_case(
    case_id: str,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin_token),
):
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    sc = _json.loads(case.scorecard) if case.scorecard else None
    out = _case_to_admin_dict(case, sc)
    latest = db.query(ResponseDraft).filter(ResponseDraft.case_id == case_id) \
        .order_by(ResponseDraft.version.desc()).first()
    out["latest_draft"] = {
        "id": latest.id,
        "status": latest.status,
        "draft_text": latest.draft_text,
        "citations_used": latest.citations_used or [],
        "flagged_citations": latest.flagged_citations or [],
        "created_at": latest.created_at.isoformat() if latest.created_at else None,
    } if latest else None
    pj = db.query(PipelineJob).filter(PipelineJob.case_id == case_id) \
        .order_by(PipelineJob.created_at.desc()).first()
    out["pipeline_job"] = {
        "id": pj.id, "status": pj.status, "error": pj.error, "stages": pj.stages or {},
    } if pj else None
    return out
```

- [ ] **Step 2: Admin UI — nav tab + view** in `admin/index.html`.

Inside `<nav class="topbar-nav">`, after the "Ärenden" button, add:

```html
    <button class="nav-tab" data-view="review">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 11 12 14 22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
      Granskning
    </button>
```

Before `<script src="app.js"></script>`, add:

```html
<!-- ── REVIEW VIEW ─────────────────────────────────── -->
<div id="view-review" class="view" style="display:none">
  <div class="layout">
    <div class="left">
      <div class="left-head">
        <div class="left-title">Granskningskö <span>· <span id="reviewCount">…</span> st</span></div>
      </div>
      <div class="case-list" id="reviewList">
        <div style="padding:24px;color:var(--muted)">Laddar…</div>
      </div>
    </div>
    <div class="right" id="reviewRight">
      <div class="right-empty"><p>Välj ett ärende för att granska scorecard och utkast.</p></div>
    </div>
  </div>
</div>
```

- [ ] **Step 3: Admin UI — logic** in `admin/app.js`.

In `switchView`, after the `if (view === "cases" ...)` line, add:

```js
  if (view === "review") loadReview();
```

Append before the `// ── Init` section:

```js
// ── Review queue ─────────────────────────────────────
const PRIO_ORDER = { high: 0, medium: 1, low: 2 };

async function loadReview() {
  const data = await apiFetch("/admin/cases?status=needs_review&limit=100");
  const cases = data.cases.sort((a, b) => {
    const pa = PRIO_ORDER[a.scorecard?.priority] ?? 3;
    const pb = PRIO_ORDER[b.scorecard?.priority] ?? 3;
    if (pa !== pb) return pa - pb;
    return (b.scorecard?.claim_strength ?? 0) - (a.scorecard?.claim_strength ?? 0);
  });
  document.getElementById("reviewCount").textContent = cases.length;
  const list = document.getElementById("reviewList");
  list.innerHTML = cases.length
    ? cases.map(renderCaseRow).join("")
    : '<div style="padding:24px;color:var(--muted);text-align:center">Inget att granska</div>';
  list.querySelectorAll(".case-row").forEach(row => {
    row.addEventListener("click", () => openReviewCase(row.dataset.id));
  });
}

function renderFlagged(refs) {
  if (!refs || !refs.length) return "";
  return `<div class="info-card full">
    <div class="info-card-title">⚠️ Overifierade hänvisningar</div>
    <p class="description-text">${refs.join(", ")} — kunde inte verifieras mot kunskapsbasen. Kontrollera manuellt.</p>
  </div>`;
}

async function openReviewCase(id) {
  const right = document.getElementById("reviewRight");
  right.innerHTML = '<div style="padding:24px;color:var(--muted)">Laddar…</div>';
  const c = await apiFetch(`/admin/cases/${id}`);
  const draft = c.latest_draft;
  const flaggedDraft = draft?.flagged_citations?.length
    ? ` · ⚠️ ${draft.flagged_citations.length} overifierade citat` : "";
  right.innerHTML = `
    <div class="detail-header">
      <div>
        <div class="detail-id">${c.id}</div>
        <div class="detail-name">${c.customer_name || "Okänd kund"}</div>
        <div class="detail-sub">${c.insurance_company || "—"} · ${c.damage_category || "—"}</div>
      </div>
      <div style="display:flex;gap:8px">
        <button class="btn-regen" id="approveBtn">✓ Godkänn</button>
        <button class="btn-regen" id="rejectBtn">✕ Avvisa</button>
      </div>
    </div>
    ${renderScorecard(c.scorecard)}
    ${renderFlagged(c.scorecard?.flagged_references)}
    ${draft ? `
      <div class="info-card full">
        <div class="info-card-title">Utkast (${draft.status})${flaggedDraft}</div>
        <p class="description-text" style="white-space:pre-wrap">${draft.draft_text || "—"}</p>
      </div>` : '<div class="info-card full"><div class="info-card-title">Utkast</div><p class="description-text">Inget utkast genererades — hantera manuellt.</p></div>'}
  `;
  document.getElementById("approveBtn").addEventListener("click", () => reviewAction(id, "approve"));
  document.getElementById("rejectBtn").addEventListener("click", () => reviewAction(id, "reject"));
}

async function reviewAction(id, action) {
  await apiFetch(`/admin/cases/${id}/review`, { method: "POST", body: JSON.stringify({ action }) });
  document.getElementById("reviewRight").innerHTML = '<div class="right-empty"><p>Klart ✓</p></div>';
  loadReview();
}
```

Also guard `renderScorecard` against a degraded (null-strength) scorecard — at its top, after the `if (!sc) return "";` line, add:

```js
  if (sc.claim_strength == null) {
    return `<div class="scorecard"><div class="sc-title">AI Scorecard</div>
      <div class="sc-error">Scorecard kunde inte genereras automatiskt (degraderat läge).</div></div>`;
  }
```

- [ ] **Step 4: Verify + commit**

Run: `python3 -c "from app.main import app; print('ok')" && python3 -m pytest tests/ -q` → `ok`, all PASS.
Then `node --check ../admin/app.js` → no syntax errors.

```bash
git add app/main.py ../admin/index.html ../admin/app.js
git commit -m "feat: review queue — approve/reject API and admin Granskning view"
```

---

### Task 9: Scorecard evals

**Files:**
- Create: `backend/evals/run_scorecard_evals.py`

- [ ] **Step 1: Create `backend/evals/run_scorecard_evals.py`**

```python
"""Score the golden set with the unified scorecard. Live LLM + Voyage calls.

Usage (from backend/):
    python3 evals/run_scorecard_evals.py            # all cases
    python3 evals/run_scorecard_evals.py --limit 2  # smoke run

Band-match is reported only for specs that carry an "expected_band"
("stark"|"medel"|"svag") label — added by the legal team in golden_cases.json.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db import SessionLocal, init_db
from app.scorecard import build_scorecard

GOLDEN = Path(__file__).parent / "golden_cases.json"
RESULTS_DIR = Path(__file__).parent / "results"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    init_db()
    specs = json.loads(GOLDEN.read_text())
    if args.limit:
        specs = specs[: args.limit]

    db = SessionLocal()
    rows = []
    try:
        for spec in specs:
            fields = {
                "customer_name": "Eval Person",
                "customer_email": "eval@example.se",
                "customer_phone": "",
                "property_address": "",
                "insurance_policy_number": "",
                "damage_category": spec["damage_category"],
                "damage_description": spec["damage_description"],
                "insurance_company": spec["insurance_company"],
                "claim_amount": spec.get("claim_amount"),
                "insurer_decision": spec.get("insurer_decision"),
                "insurer_amount": spec.get("insurer_amount"),
                "insurer_reason": spec.get("insurer_reason"),
            }
            t0 = time.time()
            sc = build_scorecard(db, fields)
            resolved = len(sc["arn_references"]) + len(sc["lagrum_references"])
            flagged = len(sc["flagged_references"])
            expected = spec.get("expected_band")
            rows.append({
                "name": spec["name"],
                "degraded": sc["degraded"],
                "claim_strength": sc["claim_strength"],
                "band": sc["strength_band"],
                "expected_band": expected,
                "band_match": (sc["strength_band"] == expected) if expected else None,
                "resolved_refs": resolved,
                "flagged_refs": flagged,
                "flagged_list": sc["flagged_references"],
                "secs": round(time.time() - t0, 1),
            })
            print(f"{spec['name']}: strength={sc['claim_strength']} band={sc['strength_band']} "
                  f"resolved={resolved} flagged={flagged} degraded={sc['degraded']}")
    finally:
        db.close()

    total = len(rows)
    completed = sum(1 for r in rows if not r["degraded"])
    resolved = sum(r["resolved_refs"] for r in rows)
    flagged = sum(r["flagged_refs"] for r in rows)
    labeled = [r for r in rows if r["band_match"] is not None]
    matches = sum(1 for r in labeled if r["band_match"])
    pct = round(100 * resolved / (resolved + flagged)) if resolved + flagged else 100
    print(f"\ncompletion: {completed}/{total}")
    print(f"citation resolution: {resolved}/{resolved + flagged} ({pct}%)")
    if labeled:
        print(f"band match: {matches}/{len(labeled)}")
    else:
        print("band match: no expected_band labels yet — legal team to add to golden_cases.json")

    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"scorecard-{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    print(f"results → {out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke run (needs API keys in `.env`)**

Run: `python3 evals/run_scorecard_evals.py --limit 2`
Expected: 2 lines with strength/band per case, `completion: 2/2`, citation resolution reported, results file written.

- [ ] **Step 3: Commit**

```bash
git add evals/run_scorecard_evals.py
git commit -m "feat: scorecard golden-set eval — completion, citation resolution, band match"
```

---

### Task 10: ARN corpus expansion (operational batch run)

No new code — run the existing law-pipeline at scale. Costs OpenRouter + Voyage tokens and real time (Voyage sleeps 22s between batches); run in background.

- [ ] **Step 1: Run the pipeline** (target: a few hundred property/insurance decisions)

```bash
cd /Users/leo-mac/claude-code/Swiftclaim/law-pipeline
source .venv/bin/activate
python main.py --limit 300
```

If the scraper or processor fails partway, re-run with `--skip-scrape` to resume processing the already-downloaded PDFs.

- [ ] **Step 2: Verify vault growth**

```bash
ls /Users/leo-mac/claude-code/Swiftclaim/swiftclaim-obsidian/ARN | wc -l
```
Expected: substantially more than 36. Spot-check 2-3 new files for frontmatter (`case_id`, `category`, `outcome`) and no PII.

- [ ] **Step 3: Reindex + import** (backend running: `python backend/run.py`)

```bash
TOKEN=$(curl -s -X POST localhost:8000/api/auth/login -H 'Content-Type: application/json' -d '{"password":"<admin password>"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
curl -X POST localhost:8000/api/reindex -H "Authorization: Bearer $TOKEN"
curl localhost:8000/api/reindex/status -H "Authorization: Bearer $TOKEN"   # poll until done
curl -X POST localhost:8000/api/arn/import                                  # sync ARN table
```

- [ ] **Step 4: Update CLAUDE.md running log + commit vault**

Append a dated entry to `Swiftclaim/CLAUDE.md` Running Log with the new ARN count and reindex stats.

```bash
git add swiftclaim-obsidian/ARN CLAUDE.md
git commit -m "data: ARN corpus expansion + reindex"
```

---

## Final verification

- [ ] Full suite: `cd backend && python3 -m pytest tests/ -v` — all pass (45 pre-existing minus 3 deleted scoring tests, plus ~13 new).
- [ ] Live end-to-end (needs API keys): start `python backend/run.py`, then:

```bash
curl -s -X POST localhost:8000/api/intake/analyze -H 'Content-Type: application/json' -d '{
  "customer_name": "Test Person", "customer_email": "t@example.se",
  "insurance_company": "Folksam", "damage_category": "Vattenskada",
  "damage_description": "Diskmaskinen läckte, parkettgolv skadat på 20 kvm. Bolaget gjorde 60% åldersavdrag.",
  "claim_amount": 150000, "insurer_decision": "partial", "insurer_amount": 60000,
  "insurer_reason": "Åldersavdrag enligt villkor."}'
# note the case_id, then poll:
curl -s "localhost:8000/api/pipeline-jobs?case_id=<CASE_ID>"
```

Expected: pipeline job reaches `done`; `GET /api/cases/<id>` shows `status: needs_review`, a stored scorecard, and a draft exists. Case appears in the admin Granskning tab; approve works.
- [ ] Ingestion check: drop a test `.md` into a NEW vault dir (e.g. `swiftclaim-obsidian/Domar/test.md`), `POST /api/reindex`, then `POST /api/search/law` with matching text — the new note appears in hits. Remove the test file + reindex after.
- [ ] Evals: `python3 evals/run_evals.py --limit 2` (draft) and `python3 evals/run_scorecard_evals.py --limit 2` — completion 100%, citation resolution reported.
