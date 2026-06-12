from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase

DB_PATH = Path(__file__).parent.parent / "data" / "swiftclaim.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False, "timeout": 30})


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_connection, connection_record):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=30000")
    cur.close()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def init_db():
    from app.models import Case, ARNDecision, LawSection, ResponseDraft, KnowledgeNote, DraftJob, LLMCall
    Base.metadata.create_all(bind=engine)
    _migrate(engine)


def _migrate(engine):
    from sqlalchemy import text
    with engine.connect() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(cases)"))]
        if "ai_analysis" not in cols:
            conn.execute(text("ALTER TABLE cases ADD COLUMN ai_analysis JSON"))
            conn.commit()
        draft_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(response_drafts)"))]
        for col, ddl in [
            ("flagged_citations", "ALTER TABLE response_drafts ADD COLUMN flagged_citations JSON"),
            ("evidence", "ALTER TABLE response_drafts ADD COLUMN evidence JSON"),
            ("model_used", "ALTER TABLE response_drafts ADD COLUMN model_used VARCHAR"),
            ("job_id", "ALTER TABLE response_drafts ADD COLUMN job_id VARCHAR"),
        ]:
            if col not in draft_cols:
                conn.execute(text(ddl))
        conn.commit()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()