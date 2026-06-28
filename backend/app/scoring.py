from __future__ import annotations
import json
import os
import re
from pathlib import Path
from typing import Any

import httpx

from app.wiki_index import get_index, get_decision_text

DEEPSEEK_V4_BASE = "https://api.deepseek.com/v1"
DEEPSEEK_V4_MODEL = "deepseek-v4-pro"


def _get_api_key() -> str:
    key = os.environ.get("DEEPSEEK_V4_API_KEY", "")
    if key:
        return key
    env_file = Path(__file__).parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("DEEPSEEK_V4_API_KEY="):
                return line.split("=", 1)[1].strip()
    return ""


def _call_deepseek_v4(prompt: str, max_tokens: int = 512) -> str:
    r = httpx.post(
        f"{DEEPSEEK_V4_BASE}/chat/completions",
        headers={
            "Authorization": f"Bearer {_get_api_key()}",
            "Content-Type": "application/json",
        },
        json={
            "model": DEEPSEEK_V4_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
        },
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _parse_json_from_response(text: str) -> dict[str, Any]:
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    match = re.search(r"\[.*?\]", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    raise ValueError(f"No valid JSON found in response: {text[:300]}")


def _select_relevant_decisions(index: str, case_summary: str) -> list[str]:
    prompt = f"""Du är en svensk försäkringsjurist. Givet detta ärende, identifiera de 3-5 mest relevanta ARN-beslut från indexet nedan.

## Ärende
{case_summary}

## ARN Wiki Index
{index}

Returnera ENBART en JSON-lista med ARN-ID:n (bara siffrorna, t.ex. ["2020-08495", "2019-04350"]). Inget annat."""

    response = _call_deepseek_v4(prompt, max_tokens=200)
    try:
        result = _parse_json_from_response(response)
        if isinstance(result, list):
            return [str(x) for x in result]
    except ValueError:
        pass
    return re.findall(r"\d{4}-\d{5}", response)


def _build_case_summary(case: dict) -> str:
    return "\n".join([
        f"Skadetyp: {case.get('damage_category', '—')}",
        f"Försäkringsbolag: {case.get('insurance_company', '—')}",
        f"Yrkat belopp: {case.get('claim_amount', '—')} kr",
        f"Erbjudet belopp: {case.get('insurer_amount', '—')} kr",
        f"Beslut: {case.get('insurer_decision', '—')}",
        f"Anledning från bolaget: {case.get('insurer_reason', '—')}",
        f"Beskrivning: {case.get('damage_description', '—')}",
    ])


def generate_scorecard(case: dict) -> dict[str, Any]:
    """Two-pass LLM Wiki scoring. case is a dict of Case model fields."""
    case_summary = _build_case_summary(case)
    index = get_index()

    arn_ids = _select_relevant_decisions(index, case_summary)

    decision_blocks = []
    for arn_id in arn_ids[:5]:
        text = get_decision_text(arn_id)
        if text:
            decision_blocks.append(f"### ARN {arn_id}\n{text}")

    decisions_block = (
        "\n\n".join(decision_blocks)
        if decision_blocks
        else "Inga direkta precedenter hittades i databasen."
    )

    scoring_prompt = f"""Du är en expert på svensk försäkringsrätt. Bedöm följande ärende mot ARN-praxis.

## Ärende
{case_summary}

## Relevanta ARN-beslut
{decisions_block}

## Uppgift
Returnera ENBART ett JSON-objekt med dessa exakta fält:
{{
  "claim_strength": <heltal 0-100>,
  "win_probability": "<procent som sträng, t.ex. '68%'>",
  "priority": "<'high', 'medium' eller 'low'>",
  "recommended_action": "<max 2 meningar, hänvisa till specifikt ARN-beslut om möjligt>",
  "key_factors": ["<faktor 1>", "<faktor 2>", "<faktor 3>"],
  "arn_references": {json.dumps(arn_ids)}
}}"""

    response = _call_deepseek_v4(scoring_prompt, max_tokens=800)
    scorecard = _parse_json_from_response(response)

    strength = int(scorecard.get("claim_strength", 0))
    if strength >= 70:
        scorecard["priority"] = "high"
    elif strength >= 40:
        scorecard["priority"] = "medium"
    else:
        scorecard["priority"] = "low"

    return scorecard
