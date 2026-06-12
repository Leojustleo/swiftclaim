import re
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.db import init_db, get_db
from app.models import Case, ARNDecision, LawSection as LawSectionModel, ResponseDraft, KnowledgeNote, DraftJob
from app.schemas import (
    CaseCreate, CaseUpdate, CaseOut,
    ARNOut, LawSectionOut,
    ResponseDraftOut, DraftJobOut,
    KnowledgeNoteCreate, KnowledgeNoteOut,
    DraftRequest, RAGQuery, BulkARNImport,
    IntakeAnalyzeRequest, IntakeAnalysisOut,
    AskRequest, AskOut,
)
from app.rag import search_law, search_precedents
from app.law_importer import get_law_section, fetch_riksdagen_law, CORE_SECTIONS, SFS_MAP
from app.intake_ai import analyze as run_intake_analysis
from app.draft_ai import create_job, run_draft_job
from app.qa_ai import ask as run_ask
from app.llm import LLMError

app = FastAPI(title="Swiftclaim API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()
    db = next(get_db())
    try:
        _seed_laws(db)
        stuck = db.query(DraftJob).filter(DraftJob.status.notin_(["done", "failed"]))
        stuck.update({"status": "failed", "error": "server restarted"}, synchronize_session=False)
        db.commit()
    finally:
        db.close()


def _seed_laws(db: Session):
    existing = db.query(LawSectionModel).count()
    if existing > 0:
        return
    for short, chap, para in CORE_SECTIONS:
        ref = f"{short} {chap} kap {para} \u00a7" if chap else f"{short} {para} \u00a7"
        try:
            ls = get_law_section(ref)
            if ls:
                db.add(LawSectionModel(
                    statute_name=ls.statute_name,
                    sfs_id=ls.sfs_id,
                    full_name=ls.full_name,
                    chapter=ls.chapter,
                    paragraph=ls.paragraph,
                    full_reference=ls.full_reference,
                    body_html=ls.body_html,
                    body_text=ls.body_text,
                    source_url=ls.source_url,
                ))
        except Exception:
            pass
    db.commit()


@app.get("/api/cases", response_model=List[CaseOut])
def list_cases(status: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(Case)
    if status:
        q = q.filter(Case.status == status)
    cases = q.order_by(Case.updated_at.desc()).all()
    return [CaseOut.model_validate(c) for c in cases]


@app.get("/api/cases/{case_id}", response_model=CaseOut)
def get_case(case_id: str, db: Session = Depends(get_db)):
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")
    return CaseOut.model_validate(case)


@app.post("/api/cases", response_model=CaseOut, status_code=201)
def create_case(data: CaseCreate, db: Session = Depends(get_db)):
    case = db.query(Case).filter(Case.id == data.id).first()
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
    return CaseOut.model_validate(case)


@app.patch("/api/cases/{case_id}", response_model=CaseOut)
def update_case(case_id: str, data: CaseUpdate, db: Session = Depends(get_db)):
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")
    for key, val in data.model_dump(exclude_unset=True).items():
        setattr(case, key, val)
    case.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(case)
    return CaseOut.model_validate(case)


@app.delete("/api/cases/{case_id}")
def delete_case(case_id: str, db: Session = Depends(get_db)):
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")
    db.delete(case)
    db.commit()
    return {"ok": True}


@app.get("/api/arn")
def list_arn(
    category: Optional[str] = None,
    outcome: Optional[str] = None,
    keyword: Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = db.query(ARNDecision)
    if category:
        q = q.filter(ARNDecision.category == category)
    if outcome:
        q = q.filter(ARNDecision.outcome == outcome)
    if keyword:
        q = q.filter(ARNDecision.keywords.contains(keyword))
    results = q.order_by(ARNDecision.date.desc()).all()
    return [ARNOut.model_validate(r) for r in results]


@app.get("/api/arn/{case_id}")
def get_arn(case_id: str, db: Session = Depends(get_db)):
    arn = db.query(ARNDecision).filter(ARNDecision.id == case_id).first()
    if not arn:
        raise HTTPException(404, "ARN decision not found")
    return ARNOut.model_validate(arn)


@app.post("/api/arn/import")
def import_arn(data: BulkARNImport, db: Session = Depends(get_db)):
    vault_path = Path(data.vault_path) if data.vault_path else (
        Path(__file__).parent.parent.parent / "swiftclaim-obsidian" / "ARN"
    )
    if not vault_path.exists():
        raise HTTPException(400, f"Vault path not found: {vault_path}")

    imported = 0
    for md in vault_path.glob("*.md"):
        text = md.read_text(encoding="utf-8").strip()
        frontmatter, body = _parse_yaml_frontmatter(text)

        case_id = frontmatter.get("case_id", "")
        if not case_id:
            case_id = re.sub(r"^ARN\s+", "", md.stem)

        existing = db.query(ARNDecision).filter(ARNDecision.id == case_id).first()
        if existing and body.strip():
            existing.body_markdown = body
            existing.category = frontmatter.get("category", existing.category)
            existing.outcome = frontmatter.get("outcome", existing.outcome)
            existing.legal_basis = frontmatter.get("legal_basis", [])
            existing.keywords = frontmatter.get("keywords", [])
        elif not existing:
            db.add(ARNDecision(
                id=case_id,
                filename=md.name,
                category=frontmatter.get("category", ""),
                subcategory=frontmatter.get("subcategory", ""),
                date=frontmatter.get("date", ""),
                outcome=frontmatter.get("outcome", ""),
                insurer=frontmatter.get("insurer", ""),
                damage_type=frontmatter.get("damage_type", ""),
                claim_amount_sek=frontmatter.get("claim_amount_sek"),
                legal_basis=frontmatter.get("legal_basis", []),
                keywords=frontmatter.get("keywords", []),
                body_markdown=body,
                raw_text="",
            ))
        imported += 1

    db.commit()
    return {"imported": imported}


@app.get("/api/laws", response_model=List[LawSectionOut])
def list_laws(statute: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(LawSectionModel)
    if statute:
        q = q.filter(LawSectionModel.statute_name == statute)
    laws = q.order_by(LawSectionModel.statute_name, LawSectionModel.chapter, LawSectionModel.paragraph).all()
    return [LawSectionOut.model_validate(l) for l in laws]


@app.get("/api/laws/{reference:path}", response_model=LawSectionOut)
def get_law(reference: str, db: Session = Depends(get_db)):
    law = db.query(LawSectionModel).filter(LawSectionModel.full_reference == reference).first()
    if law:
        return LawSectionOut.model_validate(law)
    ls = get_law_section(reference)
    if not ls:
        raise HTTPException(404, f"Law section not found: {reference}")
    db_law = LawSectionModel(
        statute_name=ls.statute_name,
        sfs_id=ls.sfs_id,
        full_name=ls.full_name,
        chapter=ls.chapter,
        paragraph=ls.paragraph,
        full_reference=ls.full_reference,
        body_html=ls.body_html,
        body_text=ls.body_text,
        source_url=ls.source_url,
    )
    db.add(db_law)
    db.commit()
    db.refresh(db_law)
    return LawSectionOut.model_validate(db_law)


@app.get("/api/laws-riksdagen/{sfs_id}")
def get_law_riksdagen(sfs_id: str):
    result = fetch_riksdagen_law(sfs_id)
    if not result:
        raise HTTPException(404, f"Law not found in Riksdagen API: {sfs_id}")
    return result


@app.post("/api/intake/analyze", response_model=IntakeAnalysisOut)
def analyze_intake(req: IntakeAnalyzeRequest, db: Session = Depends(get_db)):
    return run_intake_analysis(req.model_dump(), db)


@app.post("/api/search/law")
def search_law_endpoint(query: RAGQuery):
    hits = search_law(query.question, k=query.top_k)
    return {"query": query.question, "hits": hits}


@app.post("/api/search/precedents/{case_id}")
def search_precedents_endpoint(case_id: str, query: RAGQuery, db: Session = Depends(get_db)):
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")

    search_text = f"{case.damage_description[:300]} {case.insurance_company} {query.question}"
    hits = search_precedents(case.damage_category, search_text, k=query.top_k)
    return {"case_id": case_id, "hits": hits}


@app.post("/api/draft", status_code=202)
def start_draft(req: DraftRequest, background: BackgroundTasks, db: Session = Depends(get_db)):
    case = db.query(Case).filter(Case.id == req.case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")
    job = create_job(db, req.case_id, req.strategy, req.additional_context)
    background.add_task(run_draft_job, job.id)
    return {"job_id": job.id, "status": job.status}


def _job_out(db: Session, job: DraftJob) -> DraftJobOut:
    draft = db.query(ResponseDraft).filter(ResponseDraft.id == job.draft_id).first() if job.draft_id else None
    out = DraftJobOut.model_validate(job)
    out.draft = ResponseDraftOut.model_validate(draft) if draft else None
    return out


@app.get("/api/draft-jobs/{job_id}", response_model=DraftJobOut)
def get_draft_job(job_id: str, db: Session = Depends(get_db)):
    job = db.query(DraftJob).filter(DraftJob.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    return _job_out(db, job)


@app.get("/api/draft-jobs", response_model=Optional[DraftJobOut])
def get_latest_draft_job(case_id: str, db: Session = Depends(get_db)):
    job = db.query(DraftJob).filter(DraftJob.case_id == case_id) \
        .order_by(DraftJob.created_at.desc()).first()
    return _job_out(db, job) if job else None


@app.post("/api/ask", response_model=AskOut)
def ask_endpoint(req: AskRequest, db: Session = Depends(get_db)):
    case = db.query(Case).filter(Case.id == req.case_id).first() if req.case_id else None
    if req.case_id and not case:
        raise HTTPException(404, "Case not found")
    try:
        return run_ask(db, req.question, case)
    except LLMError as e:
        raise HTTPException(503, f"AI-tj\u00e4nsten \u00e4r inte tillg\u00e4nglig just nu: {e}")


@app.get("/api/draft/{case_id}", response_model=List[ResponseDraftOut])
def list_drafts(case_id: str, db: Session = Depends(get_db)):
    drafts = db.query(ResponseDraft).filter(
        ResponseDraft.case_id == case_id
    ).order_by(ResponseDraft.version.desc()).all()
    return drafts


@app.get("/api/notes", response_model=List[KnowledgeNoteOut])
def list_notes(note_type: Optional[str] = None, case_id: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(KnowledgeNote)
    if note_type:
        q = q.filter(KnowledgeNote.note_type == note_type)
    if case_id:
        q = q.filter(KnowledgeNote.case_id == case_id)
    notes = q.order_by(KnowledgeNote.updated_at.desc()).all()
    return [KnowledgeNoteOut.model_validate(n) for n in notes]


@app.post("/api/notes", response_model=KnowledgeNoteOut, status_code=201)
def create_note(data: KnowledgeNoteCreate, db: Session = Depends(get_db)):
    note = KnowledgeNote(**data.model_dump())
    db.add(note)
    db.commit()
    db.refresh(note)
    return KnowledgeNoteOut.model_validate(note)


@app.patch("/api/notes/{note_id}", response_model=KnowledgeNoteOut)
def update_note(note_id: str, data: KnowledgeNoteCreate, db: Session = Depends(get_db)):
    note = db.query(KnowledgeNote).filter(KnowledgeNote.id == note_id).first()
    if not note:
        raise HTTPException(404, "Note not found")
    for key, val in data.model_dump(exclude_unset=True).items():
        setattr(note, key, val)
    note.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(note)
    return KnowledgeNoteOut.model_validate(note)


def _parse_yaml_frontmatter(text: str):
    data = {}
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            fm = parts[1].strip()
            body = parts[2].strip()
            for line in fm.split("\n"):
                line = line.strip()
                if ":" in line:
                    key, _, val = line.partition(":")
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if val == "":
                        data[key] = []
                    elif val in ("null", "~"):
                        data[key] = None
                    elif val.isdigit():
                        data[key] = int(val)
                    else:
                        data[key] = val
    return data, body


@app.get("/api/status")
def status():
    return {"status": "ok", "service": "Swiftclaim"}