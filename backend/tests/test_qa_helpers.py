from app.qa_ai import arn_stats, heuristic_mode


def test_heuristic_mode_broad_vs_lookup():
    assert heuristic_mode("Vilka är de vanligaste misstagen konsumenter gör?") == "broad"
    assert heuristic_mode("Hur många ärenden vinner konsumenten?") == "broad"
    assert heuristic_mode("Finns det mönster i ARN-besluten om vattenskador?") == "broad"
    assert heuristic_mode("Vad säger FAL 4 kap 6 § om säkerhetsföreskrifter?") == "lookup"
    assert heuristic_mode("Får bolaget göra åldersavdrag på golv?") == "lookup"


def test_arn_stats_aggregates():
    rows = [
        {"outcome": "consumer_won", "category": "försäkring", "legal_basis": ["36 § avtalslagen"], "keywords": ["åldersavdrag"]},
        {"outcome": "consumer_lost", "category": "försäkring", "legal_basis": ["36 § avtalslagen", "FAL 4 kap 6 §"], "keywords": ["nedsättning", "åldersavdrag"]},
        {"outcome": "consumer_won", "category": "resor", "legal_basis": [], "keywords": []},
    ]
    s = arn_stats(rows)
    assert s["total"] == 3
    assert s["outcomes"]["consumer_won"] == 2
    assert s["by_category"]["försäkring"]["consumer_lost"] == 1
    assert s["top_legal_basis"][0] == ("36 § avtalslagen", 2)
    assert s["top_keywords"][0] == ("åldersavdrag", 2)
