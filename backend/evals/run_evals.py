"""Run the draft pipeline against the golden set. Live LLM + Voyage calls.

Usage (from backend/):
    python evals/run_evals.py            # all 10 cases
    python evals/run_evals.py --limit 3  # smoke run
    python evals/run_evals.py --keep     # keep EVAL- cases in the DB
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
from app.draft_ai import create_job, run_draft_job
from app.models import Case, DraftJob, ResponseDraft
from app.verify import normalize_lagrum

GOLDEN = Path(__file__).parent / "golden_cases.json"
RESULTS_DIR = Path(__file__).parent / "results"


def expected_hit(expected_refs, draft):
    cited = {c.lower() for c in (draft.citations_used or [])}
    evidence_titles = {d["title"].lower() for d in (draft.evidence or [])}
    for ref in expected_refs:
        norm = (normalize_lagrum(ref) or ref).lower()
        if norm in cited or norm in evidence_titles:
            return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    init_db()
    cases = json.loads(GOLDEN.read_text())
    if args.limit:
        cases = cases[: args.limit]

    rows = []
    db = SessionLocal()
    try:
        for i, spec in enumerate(cases):
            case_id = f"EVAL-{datetime.utcnow().strftime('%H%M%S')}-{i}"
            db.add(Case(
                id=case_id,
                customer_name="Eval Person", customer_email="eval@example.se",
                customer_phone="", property_address="", property_type="villa",
                insurance_company=spec["insurance_company"], insurance_policy_number="",
                insurance_type="villa", damage_category=spec["damage_category"],
                damage_description=spec["damage_description"], damage_date="2026-05-01",
                claim_amount=spec.get("claim_amount"),
                insurer_decision=spec.get("insurer_decision"),
                insurer_amount=spec.get("insurer_amount"),
                insurer_reason=spec.get("insurer_reason"),
                tags=["eval"],
            ))
            db.commit()
            job = create_job(db, case_id, "maximize_payout", "")
            t0 = time.time()
            run_draft_job(job.id)
            elapsed = round(time.time() - t0, 1)
            db.expire_all()
            job = db.query(DraftJob).filter(DraftJob.id == job.id).first()
            draft = db.query(ResponseDraft).filter(ResponseDraft.id == job.draft_id).first() if job.draft_id else None
            n_cited = len(draft.citations_used or []) if draft else 0
            n_flagged = len(draft.flagged_citations or []) if draft else 0
            rows.append({
                "name": spec["name"],
                "job_status": job.status,
                "draft_status": draft.status if draft else "-",
                "cited": n_cited,
                "flagged": n_flagged,
                "validity": round(n_cited / (n_cited + n_flagged), 2) if (n_cited + n_flagged) else 0.0,
                "expected_hit": expected_hit(spec["expected_refs"], draft) if draft else False,
                "model": draft.model_used if draft else "-",
                "seconds": elapsed,
                "error": (job.error or "")[:120],
            })
            print(f"[{i + 1}/{len(cases)}] {spec['name']}: {job.status} ({elapsed}s)")
        if not args.keep:
            for c in db.query(Case).filter(Case.id.like("EVAL-%")).all():
                db.delete(c)
            db.commit()
    finally:
        db.close()

    done = [r for r in rows if r["job_status"] == "done"]
    summary = {
        "completion_rate": round(len(done) / len(rows), 2) if rows else 0,
        "avg_validity": round(sum(r["validity"] for r in done) / len(done), 2) if done else 0,
        "expected_ref_hit_rate": round(sum(r["expected_hit"] for r in done) / len(done), 2) if done else 0,
        "needs_review_rate": round(sum(r["draft_status"] == "needs_review" for r in done) / len(done), 2) if done else 0,
        "avg_seconds": round(sum(r["seconds"] for r in done) / len(done), 1) if done else 0,
    }

    RESULTS_DIR.mkdir(exist_ok=True)
    report = RESULTS_DIR / f"{datetime.utcnow().strftime('%Y-%m-%d-%H%M')}.md"
    lines = ["# Draft pipeline eval", "", f"Run: {datetime.utcnow().isoformat()} · {len(rows)} cases", "",
             "| case | job | draft | cited | flagged | validity | expected hit | model | s |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['name']} | {r['job_status']} | {r['draft_status']} | {r['cited']} | "
                     f"{r['flagged']} | {r['validity']} | {'OK' if r['expected_hit'] else 'MISS'} | {r['model']} | {r['seconds']} |")
    lines += ["", "## Summary", "", "```json", json.dumps(summary, indent=2), "```"]
    if any(r["error"] for r in rows):
        lines += ["", "## Errors", ""] + [f"- {r['name']}: {r['error']}" for r in rows if r["error"]]
    report.write_text("\n".join(lines))
    print(f"\nSummary: {json.dumps(summary)}")
    print(f"Report: {report}")


if __name__ == "__main__":
    main()
