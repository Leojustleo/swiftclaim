from sqlalchemy import inspect

from app.db import engine, init_db


def test_new_tables_and_columns_exist():
    init_db()
    insp = inspect(engine)
    assert "draft_jobs" in insp.get_table_names()
    assert "llm_calls" in insp.get_table_names()
    draft_cols = {c["name"] for c in insp.get_columns("response_drafts")}
    assert {"flagged_citations", "evidence", "model_used", "job_id"} <= draft_cols
