import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, List

import httpx
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.db import init_db, get_db
from app.models import Case, ARNDecision, LawSection as LawSectionModel, ResponseDraft, KnowledgeNote
from app.schemas import (
    CaseCreate, CaseUpdate, CaseOut,
    ARNOut, LawSectionOut,
    ResponseDraftOut,
    KnowledgeNoteCreate, KnowledgeNoteOut,
    DraftRequest, RAGQuery, BulkARNImport,
    IntakeAnalyzeRequest, IntakeAnalysisOut,
)
from app.rag import search_law, search_precedents
from app.law_importer import get_law_section, fetch_riksdagen_law, CORE_SECTIONS, SFS_MAP
from app.intake_ai import analyze as run_intake_analysis, LLM_URL, CHAT_MODEL, _get_llm_key

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


DRAFT_SYSTEM_PROMPT = u"""Du \u00e4r en erfaren svensk f\u00f6rs\u00e4kringsjurist som arbetar f\u00f6r Swiftclaim \u2014 en tj\u00e4nst som hj\u00e4lper konsumenter att f\u00e5 maximal ers\u00e4ttning fr\u00e5n sitt f\u00f6rs\u00e4kringsbolag.

Din uppgift: Skriv ett professionellt, juridiskt v\u00e4lgrundat svar till f\u00f6rs\u00e4kringsbolaget som ifr\u00e5gas\u00e4tter deras beslut och kr\u00e4ver h\u00f6gre ers\u00e4ttning.

STRATEGI:
- Anv\u00e4nd alltid relevanta lagrum som st\u00f6d (FAL, Avtalslagen, etc.)
- Citera relevanta ARN-beslut som prejudikat
- Peka p\u00e5 brister i bolagets utredning eller motivering
- Var specifik om belopp och ber\u00e4kningsgrunder
- H\u00e5ll en professionell men best\u00e4md ton
- Om bolaget har nekat ers\u00e4ttning: kr\u00e4v en konkret redovisning av vilka villkor de \u00e5beropar
- Om bolaget har satt ned ers\u00e4ttning: ifr\u00e5gas\u00e4tt neds\u00e4ttningens storlek och be om specifik motivering
- N\u00e4mn alltid konsumentens r\u00e4ttigheter enligt FAL:s tvingande regler

FORMAT:
Svara med ett komplett brevutkast p\u00e5 svenska. B\u00f6rja med \u00e4renderubrik och \"Till [f\u00f6rs\u00e4kringsbolag]\".
Inkludera:
1. En inledning som sammanfattar \u00e4rendet och bestrider beslutet
2. Juridisk argumentation med lagrumsh\u00e4nvisningar
3. Referens till relevant praxis (ARN-beslut)
4. Konkreta yrkanden (vad konsumenten vill ha)
5. Avslutning med tidsfrist f\u00f6r svar

Anv\u00e4nd [[wiki-l\u00e4nkar]] f\u00f6r lagrum och ARN-fall i strateginoten, men skriv ut fullst\u00e4ndiga h\u00e4nvisningar i sj\u00e4lva brevtexten."""


@app.post("/api/draft", response_model=ResponseDraftOut)
def generate_draft(req: DraftRequest, db: Session = Depends(get_db)):
    case = db.query(Case).filter(Case.id == req.case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")

    llm_key = _get_llm_key()

    search_query = f"{case.damage_category} {case.damage_description[:300]} {case.insurance_company}"
    if case.insurer_reason:
        search_query += f" {case.insurer_reason[:300]}"

    law_hits = search_law(search_query, k=6)
    arn_hits = search_precedents(case.damage_category, case.insurer_reason or case.damage_description, k=6)

    context_parts = []
    context_parts.append("### RELEVANTA LAGRUM ###\n")
    for h in law_hits:
        context_parts.append(f"**{h['title']}**\n{h['text'][:1500]}")

    context_parts.append("\n### RELEVANTA ARN-BESLUT ###\n")
    for h in arn_hits:
        context_parts.append(f"**{h['title']}** (relevans: {h['score']})\n{h['text'][:1500]}")

    context = "\n\n---\n\n".join(context_parts)

    user_msg = u"""\u00c4RENDE:
Kund: {name}
F\u00f6rs\u00e4kringsbolag: {company}
F\u00f6rs\u00e4kringsnummer: {policy}
Typ av skada: {damage_cat}
Skadebeskrivning: {desc}
Skadedatum: {damage_date}
Yrkat belopp: {claim} kr

F\u00f6rs\u00e4kringsbolagets beslut: {decision}
Bolagets motivering: {reason}
Erbjudet belopp: {amount} kr

Strategi: {strategy}
Ytterligare kontext: {context_add}

---

JURIDISK KUNSKAPSBAS:

{knowledge}

---

Skriv ett brevutkast enligt instruktionerna i system-prompten. Var specifik, juridisk, och \u00f6vertygande. Anv\u00e4nd de lagrum och ARN-fall som \u00e4r relevanta f\u00f6r just detta \u00e4rende.""".format(
        name=case.customer_name,
        company=case.insurance_company,
        policy=case.insurance_policy_number or "ok\u00e4nt",
        damage_cat=case.damage_category,
        desc=case.damage_description,
        damage_date=case.damage_date or "ok\u00e4nt",
        claim=case.claim_amount or "ej specificerat",
        decision=case.insurer_decision or "ok\u00e4nt",
        reason=case.insurer_reason or "ingen motivering angiven",
        amount=case.insurer_amount or "ej specificerat",
        strategy=req.strategy,
        context_add=req.additional_context or "ingen",
        knowledge=context,
    )

    try:
        r = httpx.post(
            LLM_URL,
            json={
                "model": CHAT_MODEL,
                "messages": [
                    {"role": "system", "content": DRAFT_SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                "max_tokens": 4000,
            },
            headers={"Authorization": f"Bearer {llm_key}"},
            timeout=180,
        )
        if r.status_code != 200:
            raise HTTPException(500, f"LLM API error: {r.text[:500]}")
        raw = r.json()["choices"][0]["message"]["content"]

        strategy = ""
        draft_text = raw
        if "## Strategi" in raw:
            parts = raw.split("## Brevutkast", 1)
            if len(parts) == 2:
                strategy = parts[0].replace("## Strategi", "").strip()
                draft_text = parts[1].strip()
        elif "## BREVUTKAST" in raw:
            parts = raw.split("## BREVUTKAST", 1)
            if len(parts) == 2:
                strategy = parts[0].strip()
                draft_text = parts[1].strip()

        wiki_links = re.findall(r"\[\[([^\]]+)\]\]", raw)

        existing = db.query(ResponseDraft).filter(
            ResponseDraft.case_id == req.case_id
        ).order_by(ResponseDraft.version.desc()).first()
        version = (existing.version + 1) if existing else 1

        draft = ResponseDraft(
            case_id=req.case_id,
            version=version,
            strategy=strategy or req.strategy,
            draft_text=draft_text,
            citations_used=wiki_links,
            status="draft",
        )
        db.add(draft)
        case.status = "draft"
        case.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(draft)
        return draft

    except httpx.RequestError as e:
        raise HTTPException(500, f"API request failed: {e}")
    except Exception as e:
        raise HTTPException(500, str(e))


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