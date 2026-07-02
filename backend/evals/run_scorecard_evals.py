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
