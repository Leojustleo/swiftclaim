import datetime
from sqlalchemy import Column, String, Text, Integer, Float, Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from app.db import Base


class Case(Base):
    __tablename__ = "cases"

    id = Column(String, primary_key=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    customer_name = Column(String)
    customer_email = Column(String)
    customer_phone = Column(String)
    property_address = Column(String)
    property_type = Column(String)  # villa, bostadsratt, hyresratt, fritidshus, brf

    insurance_company = Column(String)
    insurance_policy_number = Column(String)
    insurance_type = Column(String)  # hem, villa, fritidshus, brf

    damage_category = Column(String)  # water, fire, theft, storm, mold, liability, other
    damage_description = Column(Text)
    damage_date = Column(String)
    claim_amount = Column(Integer, nullable=True)
    insurer_decision = Column(String, nullable=True)  # paid, partial, denied, pending
    insurer_amount = Column(Integer, nullable=True)
    insurer_reason = Column(Text, nullable=True)

    status = Column(String, default="intake")  # intake, analysis, draft, negotiation, appealed, closed
    stage = Column(String, default="new")
    priority = Column(String, default="normal")
    assigned_to = Column(String, default="swiftclaim-bot")
    outcome = Column(String, nullable=True)

    tags = Column(JSON, default=[])
    ai_analysis = Column(JSON, nullable=True)
    scorecard = Column(Text, nullable=True)

    drafts = relationship("ResponseDraft", back_populates="case", cascade="all, delete-orphan")
    knowledge_notes = relationship("KnowledgeNote", back_populates="case", cascade="all, delete-orphan")


class ARNDecision(Base):
    __tablename__ = "arn_decisions"

    id = Column(String, primary_key=True)  # e.g. "2023-07552"
    filename = Column(String)
    category = Column(String, index=True)
    subcategory = Column(String, nullable=True)
    date = Column(String)
    outcome = Column(String, index=True)  # consumer_won, consumer_lost, partially_won
    insurer = Column(String)
    damage_type = Column(String)
    claim_amount_sek = Column(Integer, nullable=True)
    legal_basis = Column(JSON, default=[])
    keywords = Column(JSON, default=[])
    body_markdown = Column(Text)
    raw_text = Column(Text)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class LawSection(Base):
    __tablename__ = "law_sections"

    id = Column(Integer, primary_key=True, autoincrement=True)
    statute_name = Column(String, index=True)   # "FAL", "Avtalslagen", "Konsumentköplagen"
    sfs_id = Column(String, index=True)          # "2005:104"
    full_name = Column(String)
    chapter = Column(Integer, nullable=True)
    paragraph = Column(String)                   # "6"
    full_reference = Column(String, index=True)  # "FAL 4 kap 6 §"
    body_html = Column(Text)
    body_text = Column(Text)
    source_url = Column(String)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class ResponseDraft(Base):
    __tablename__ = "response_drafts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(String, ForeignKey("cases.id"))
    version = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    strategy = Column(Text)       # legal strategy notes
    draft_text = Column(Text)     # the actual draft reply
    citations_used = Column(JSON, default=[])   # laws and ARN cases cited
    status = Column(String, default="draft")     # draft, needs_review, reviewed, sent, archived
    flagged_citations = Column(JSON, default=[])
    evidence = Column(JSON, default=[])
    model_used = Column(String, nullable=True)
    job_id = Column(String, nullable=True)

    case = relationship("Case", back_populates="drafts")


class DraftJob(Base):
    __tablename__ = "draft_jobs"

    id = Column(String, primary_key=True)
    case_id = Column(String, ForeignKey("cases.id"), index=True)
    status = Column(String, default="queued")  # queued, planning, retrieving, drafting, verifying, done, failed
    stages = Column(JSON, default={})
    error = Column(Text, nullable=True)
    draft_id = Column(Integer, nullable=True)
    pipeline_version = Column(String, default="2.0")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class LLMCall(Base):
    __tablename__ = "llm_calls"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String, nullable=True, index=True)
    stage = Column(String)
    provider = Column(String)
    model = Column(String)
    status = Column(String)  # ok, error
    error = Column(Text, nullable=True)
    latency_ms = Column(Integer, default=0)
    prompt_text = Column(Text)
    response_text = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class KnowledgeNote(Base):
    __tablename__ = "knowledge_notes"

    id = Column(String, primary_key=True)
    case_id = Column(String, ForeignKey("cases.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    title = Column(String)
    content = Column(Text)
    note_type = Column(String, default="note")   # note, strategy, precedent, template
    tags = Column(JSON, default=[])

    case = relationship("Case", back_populates="knowledge_notes")