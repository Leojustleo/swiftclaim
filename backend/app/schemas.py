from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict


class CaseCreate(BaseModel):
    id: str
    customer_name: str
    customer_email: str = ""
    customer_phone: str = ""
    property_address: str = ""
    property_type: str = ""
    insurance_company: str
    insurance_policy_number: str = ""
    insurance_type: str = ""
    damage_category: str
    damage_description: str
    damage_date: str = ""
    claim_amount: Optional[int] = None
    insurer_decision: Optional[str] = None
    insurer_amount: Optional[int] = None
    insurer_reason: Optional[str] = None
    tags: List[str] = []


class CaseUpdate(BaseModel):
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None
    customer_phone: Optional[str] = None
    property_address: Optional[str] = None
    property_type: Optional[str] = None
    insurance_company: Optional[str] = None
    insurance_policy_number: Optional[str] = None
    insurance_type: Optional[str] = None
    damage_category: Optional[str] = None
    damage_description: Optional[str] = None
    damage_date: Optional[str] = None
    claim_amount: Optional[int] = None
    insurer_decision: Optional[str] = None
    insurer_amount: Optional[int] = None
    insurer_reason: Optional[str] = None
    status: Optional[str] = None
    stage: Optional[str] = None
    priority: Optional[str] = None
    assigned_to: Optional[str] = None
    outcome: Optional[str] = None
    tags: Optional[List[str]] = None


class CaseOut(BaseModel):
    id: str
    created_at: datetime
    updated_at: datetime
    customer_name: str
    customer_email: str
    customer_phone: str
    property_address: str
    property_type: str
    insurance_company: str
    insurance_policy_number: str
    insurance_type: str
    damage_category: str
    damage_description: str
    damage_date: str
    claim_amount: Optional[int]
    insurer_decision: Optional[str]
    insurer_amount: Optional[int]
    insurer_reason: Optional[str]
    status: str
    stage: str
    priority: str
    assigned_to: str
    outcome: Optional[str]
    tags: List
    ai_analysis: Optional[dict] = None

    model_config = ConfigDict(from_attributes=True)


class ARNOut(BaseModel):
    id: str
    category: str
    subcategory: Optional[str]
    date: str
    outcome: str
    insurer: str
    damage_type: str
    claim_amount_sek: Optional[int]
    legal_basis: List
    keywords: List
    body_markdown: str

    model_config = ConfigDict(from_attributes=True)


class LawSectionOut(BaseModel):
    id: int
    statute_name: str
    sfs_id: str
    full_name: str
    chapter: Optional[int]
    paragraph: str
    full_reference: str
    body_text: str
    body_html: str
    source_url: str

    model_config = ConfigDict(from_attributes=True)


class ResponseDraftCreate(BaseModel):
    case_id: str
    strategy: str = ""


class ResponseDraftOut(BaseModel):
    id: int
    case_id: str
    version: int
    created_at: datetime
    strategy: str
    draft_text: str
    citations_used: List
    status: str

    model_config = ConfigDict(from_attributes=True)


class KnowledgeNoteCreate(BaseModel):
    id: str
    title: str
    content: str
    note_type: str = "note"
    tags: List[str] = []
    case_id: Optional[str] = None


class KnowledgeNoteOut(BaseModel):
    id: str
    case_id: Optional[str]
    created_at: datetime
    updated_at: datetime
    title: str
    content: str
    note_type: str
    tags: List

    model_config = ConfigDict(from_attributes=True)


class DraftRequest(BaseModel):
    case_id: str
    additional_context: str = ""
    strategy: str = "maximize_payout"


class RAGQuery(BaseModel):
    question: str
    top_k: int = 8


class IntakeAnalyzeRequest(BaseModel):
    customer_name: str
    customer_email: str
    damage_description: str
    customer_phone: str = ""
    property_address: str = ""
    property_type: str = ""
    insurance_company: str = ""
    damage_category: str = ""
    damage_date: str = ""
    claim_amount: Optional[int] = None
    insurer_decision: Optional[str] = None
    insurer_amount: Optional[int] = None
    insurer_reason: Optional[str] = None
    tags: List[str] = []


class MatchedLaw(BaseModel):
    ref: str
    title: str
    score: float
    excerpt: str


class MatchedPrecedent(BaseModel):
    id: str
    title: str
    score: float
    excerpt: str


class IntakeAnalysisOut(BaseModel):
    case_id: str
    category: str
    strength: str
    summary: str
    key_arguments: List[str]
    missing_info: List[str]
    matched_laws: List[MatchedLaw]
    matched_precedents: List[MatchedPrecedent]
    degraded: bool
    generated_at: str


class BulkARNImport(BaseModel):
    vault_path: str = ""