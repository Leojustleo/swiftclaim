from __future__ import annotations

import re
from typing import Dict, List, Optional, Set, Tuple

STATUTE_ALIASES = {
    "fal": "FAL",
    "försäkringsavtalslagen": "FAL",
    "försäkringsavtalslag": "FAL",
    "avtalslagen": "Avtalslagen",
    "avtl": "Avtalslagen",
    "skadeståndslagen": "Skadeståndslagen",
    "skl": "Skadeståndslagen",
    "jordabalken": "Jordabalken",
    "jb": "Jordabalken",
    "bostadsrättslagen": "Bostadsrättslagen",
    "brl": "Bostadsrättslagen",
    "konsumentköplagen": "Konsumentköplagen",
    "kkl": "Konsumentköplagen",
    "konsumenttjänstlagen": "Konsumenttjänstlagen",
    "ktjl": "Konsumenttjänstlagen",
    "konsumentförsäkringslagen": "Konsumentförsäkringslagen",
    "konsumentavtalsvillkorslagen": "Konsumentavtalsvillkorslagen",
    "distansavtalslagen": "Distansavtalslagen",
    "trafikskadelagen": "Trafikskadelagen",
    "paketreselagen": "Paketreselagen",
}

ARN_RE = re.compile(r"(?:ARN\s*)?(\d{4}-\d{4,6})")
DOC_RE = re.compile(r"^DOC-\d+$", re.IGNORECASE)
_PRE_RE = re.compile(
    r"(?P<statute>[A-Za-zåäöÅÄÖ]+)\s+(?:(?P<chap>\d+)\s*kap\.?\s+)?(?P<para>\d+\s*[a-z]?)\s*§"
)
_POST_RE = re.compile(
    r"(?:(?P<chap>\d+)\s*kap\.?\s+)?(?P<para>\d+\s*[a-z]?)\s*§\s+(?P<statute>[A-Za-zåäöÅÄÖ]+)"
)


def _canonical(statute: str, chap: Optional[str], para: str) -> str:
    para = re.sub(r"(\d+)\s*([a-z])", r"\1 \2", para.strip())
    if chap:
        return f"{statute} {chap} kap {para} §"
    return f"{statute} {para} §"


def normalize_lagrum(ref: str) -> Optional[str]:
    text = (ref or "").strip()
    if not text:
        return None
    for rx in (_PRE_RE, _POST_RE):
        for m in rx.finditer(text):
            statute = STATUTE_ALIASES.get(m.group("statute").lower())
            if statute:
                return _canonical(statute, m.group("chap"), m.group("para"))
    return None


class CitationResolver:
    def __init__(self, vault_titles: Set[str], law_refs: Set[str],
                 arn_ids: Set[str], evidence_ids: Set[str]):
        self._vault = {t.lower() for t in vault_titles}
        self._laws = {r.lower() for r in law_refs}
        self._arn = set(arn_ids)
        self._evidence = {e.upper() for e in evidence_ids}

    def resolve(self, ref: str) -> Optional[Dict[str, str]]:
        ref = (ref or "").strip()
        if not ref:
            return None
        if DOC_RE.match(ref) and ref.upper() in self._evidence:
            return {"ref": ref.upper(), "kind": "evidence"}
        m = ARN_RE.search(ref)
        if m and m.group(1) in self._arn:
            return {"ref": f"ARN {m.group(1)}", "kind": "arn"}
        norm = normalize_lagrum(ref)
        if norm and (norm.lower() in self._vault or norm.lower() in self._laws):
            return {"ref": norm, "kind": "lagrum"}
        if ref.lower() in self._vault:
            return {"ref": ref, "kind": "vault"}
        return None


def verify_citations(citations: List[dict], resolver: CitationResolver) -> Tuple[List[dict], List[str]]:
    """Split citations into (verified, flagged refs). Each citation: {ref, doc_id?}."""
    verified: List[dict] = []
    flagged: List[str] = []
    seen: Set[str] = set()
    for c in citations:
        ref = (c.get("ref") or "").strip()
        doc_id = (c.get("doc_id") or "").strip()
        hit = resolver.resolve(ref) or (resolver.resolve(doc_id) if doc_id else None)
        if hit:
            out = {"ref": hit["ref"] if hit["kind"] != "evidence" else (ref or hit["ref"]),
                   "kind": hit["kind"], "doc_id": doc_id or None}
            if out["ref"].lower() not in seen:
                seen.add(out["ref"].lower())
                verified.append(out)
        elif ref and ref.lower() not in seen:
            seen.add(ref.lower())
            flagged.append(ref)
    return verified, flagged


def build_resolver(db, evidence_ids: Set[str]) -> CitationResolver:
    from app.models import ARNDecision, LawSection
    from app.rag import get_index

    notes, _ = get_index()
    vault_titles = {n["title"] for n in notes}
    arn_ids = {n["title"].replace("ARN ", "") for n in notes if n["path"].startswith("ARN/")}
    law_refs = {row[0] for row in db.query(LawSection.full_reference).all() if row[0]}
    arn_ids |= {row[0] for row in db.query(ARNDecision.id).all() if row[0]}
    return CitationResolver(vault_titles, law_refs, arn_ids, evidence_ids)
