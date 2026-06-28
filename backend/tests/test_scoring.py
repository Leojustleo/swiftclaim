import json
from unittest.mock import patch
from app.scoring import generate_scorecard, _select_relevant_decisions, _parse_json_from_response


MOCK_SCORECARD = {
    "claim_strength": 75,
    "win_probability": "65%",
    "priority": "high",
    "recommended_action": "Begär omprövning med stöd av ARN 2020-08495.",
    "key_factors": ["Underbetalt med 85 000 kr", "If tappar ofta i ARN", "Välbeskriven skada"],
    "arn_references": ["2020-08495"],
}

MOCK_CASE = {
    "damage_category": "water",
    "insurance_company": "If",
    "claim_amount": 150000,
    "insurer_amount": 65000,
    "insurer_decision": "Underbetalt",
    "insurer_reason": "Åldersavdrag på golvet",
    "damage_description": "Läckage från tvättmaskin i källaren",
}


def test_parse_json_from_response_clean():
    result = _parse_json_from_response('{"a": 1}')
    assert result == {"a": 1}


def test_parse_json_from_response_embedded():
    result = _parse_json_from_response('Here is the result:\n{"a": 1}\nDone.')
    assert result == {"a": 1}


def test_parse_json_from_response_raises_on_invalid():
    import pytest
    with pytest.raises(ValueError):
        _parse_json_from_response("no json here at all")


def test_generate_scorecard_happy_path():
    with patch("app.scoring._call_deepseek_v4") as mock_call:
        mock_call.side_effect = [
            '["2020-08495", "2019-04350"]',
            json.dumps(MOCK_SCORECARD),
        ]
        result = generate_scorecard(MOCK_CASE)

    assert result["claim_strength"] == 75
    assert result["priority"] == "high"
    assert "recommended_action" in result
    assert isinstance(result["key_factors"], list)
    assert len(result["key_factors"]) == 3


def test_generate_scorecard_enforces_priority_thresholds():
    scorecard_low = {**MOCK_SCORECARD, "claim_strength": 30, "priority": "high"}
    with patch("app.scoring._call_deepseek_v4") as mock_call:
        mock_call.side_effect = [
            '["2020-08495"]',
            json.dumps(scorecard_low),
        ]
        result = generate_scorecard(MOCK_CASE)
    assert result["priority"] == "low"


def test_generate_scorecard_medium_threshold():
    scorecard_med = {**MOCK_SCORECARD, "claim_strength": 55, "priority": "high"}
    with patch("app.scoring._call_deepseek_v4") as mock_call:
        mock_call.side_effect = [
            '["2020-08495"]',
            json.dumps(scorecard_med),
        ]
        result = generate_scorecard(MOCK_CASE)
    assert result["priority"] == "medium"
