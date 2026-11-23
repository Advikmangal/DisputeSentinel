"""Private PDF storage and deterministic evidence coverage."""
import io
import json
from fastapi import HTTPException
from pypdf import PdfReader
from sqlalchemy import select
from app.models import EvidenceDocument, ExtractedFact, Transaction

MAX_BYTES = 10_000_000
CHECKLIST = {"delivery": (30, "Proof of delivery"), "communication": (20, "Buyer communication"),
             "agreement": (20, "Terms and agreement"), "payment": (15, "Verified payment"),
             "access": (15, "Usage or access logs")}


def owned_transaction(db, merchant_id, transaction_id, lock=False):
    query = select(Transaction).where(Transaction.id == transaction_id, Transaction.merchant_id == merchant_id)
    tx = db.scalar(query.with_for_update() if lock else query)
    if tx is None:
        raise HTTPException(404, "Transaction not found.")
    return tx


def extract_pages(data):
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "PDF must be at most 10 MB.")
    if not data.startswith(b"%PDF-"):
        raise HTTPException(422, "Upload a valid PDF file.")
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted or len(reader.pages) > 50:
            raise HTTPException(422, "Use an unencrypted PDF with at most 50 pages.")
        pages, total = [], 0
        for number, page in enumerate(reader.pages, 1):
            content = page.get_contents()
            if content and len(content.get_data()) > 5_000_000:
                raise HTTPException(422, "PDF page is too complex. Export a simpler text PDF.")
            text = page.extract_text() or ""
            total += len(text)
            if total > 100_000:
                raise HTTPException(422, "PDF text exceeds 100,000 characters. Split the document.")
            pages.append({"page": number, "text": text})
        if not any(p["text"].strip() for p in pages):
            raise HTTPException(422, "No readable text found. Scanned PDFs need OCR first.")
        return pages
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(422, "This PDF could not be read.") from None


def documents(db, transaction_id):
    return db.scalars(select(EvidenceDocument).where(EvidenceDocument.transaction_id == transaction_id).order_by(EvidenceDocument.id)).all()


def facts(db, transaction_id):
    return db.scalars(select(ExtractedFact).join(EvidenceDocument).where(EvidenceDocument.transaction_id == transaction_id).order_by(ExtractedFact.id)).all()


def checked_facts(document, candidates):
    pages = {p["page"]: p["text"] for p in document_pages(document)}
    result, seen = [], set()
    for fact in candidates:
        kind = fact.fact_type if fact.supports_claim else "concern_" + fact.fact_type
        key = (kind, fact.page, fact.excerpt)
        if fact.document_id == document.id and fact.page in pages and fact.excerpt in pages[fact.page] and fact.excerpt.strip() and key not in seen:
            seen.add(key)
            result.append(ExtractedFact(document_id=document.id, fact_type=kind, page=fact.page,
                                       excerpt=fact.excerpt, value=fact.excerpt, confidence=fact.confidence))
    return result


def readiness(db, tx):
    existing = facts(db, tx.id)
    legacy = {"proof_of_delivery": "delivery", "communication_with_buyer": "communication",
              "terms_agreement": "agreement", "usage_access_logs": "access"}
    breakdown = []
    for kind, (weight, label) in CHECKLIST.items():
        strength = max((f.confidence for f in existing if legacy.get(f.fact_type, f.fact_type) == kind), default=0)
        concern = any(f.fact_type == "concern_" + kind for f in existing)
        if kind == "payment":
            strength = 1 if tx.status == "VERIFIED" else 0
        status = "review" if concern else "present" if strength >= .8 else "weak" if strength else "missing"
        breakdown.append({"key": kind, "label": label, "weight": weight, "status": status,
                          "points": weight if status == "present" else weight // 2 if status == "weak" else 0})
    return {"score": sum(x["points"] for x in breakdown), "breakdown": breakdown,
            "missing_items": [x["label"] for x in breakdown if x["status"] != "present"],
            "note": "Evidence coverage, not a prediction of winning. Review quotations and conflicting evidence."}


def document_pages(document):
    raw = json.loads(document.text_content or "[]")
    # Earlier deployments stored page strings. Retain existing evidence on upgrade.
    return [{"page": i, "text": p} if isinstance(p, str) else p for i, p in enumerate(raw, 1)]
