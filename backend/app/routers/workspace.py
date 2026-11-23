"""Merchant-scoped evidence, dispute review and dashboard APIs."""
import json
from datetime import datetime, timedelta, timezone
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import AuditLog, Dispute, DisputeResponse, EvidenceDocument, ExtractedFact, Merchant, Transaction
from app.routers.payments import get_paypal
from app.services import evidence, gemini
from app.services.auth import get_merchant_id
from app.services.paypal import PayPalError

router = APIRouter(prefix="/api", tags=["workspace"])
DB = Annotated[Session, Depends(get_db)]
MID = Annotated[int, Depends(get_merchant_id)]


def audit(db, mid, action, kind, ident, detail=None):
    db.add(AuditLog(merchant_id=mid, action=action, entity_type=kind, entity_id=ident, detail=detail or {}))


def document_out(doc):
    return {"id": doc.id, "filename": doc.filename, "size": doc.size, "uploaded_at": doc.uploaded_at,
            "pages": len(json.loads(doc.text_content or "[]"))}


@router.post("/transactions/{tid}/evidence", status_code=201)
async def upload(tid: int, request: Request, db: DB, mid: MID,
                 filename: str = Query(min_length=1, max_length=200)):
    evidence.owned_transaction(db, mid, tid, lock=True)
    if len(evidence.documents(db, tid)) >= 10:
        raise HTTPException(409, "Maximum 10 documents per transaction.")
    if request.headers.get("content-type", "").split(";")[0] != "application/pdf":
        raise HTTPException(415, "Send PDF bytes with Content-Type: application/pdf.")
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > evidence.MAX_BYTES:
            raise HTTPException(413, "PDF must be at most 10 MB.")
        data.extend(chunk)
    # Parsing is synchronous CPU work: keep it off the ASGI event loop.
    from starlette.concurrency import run_in_threadpool
    pages = await run_in_threadpool(evidence.extract_pages, bytes(data))
    name = filename.replace("\\", "/").split("/")[-1]
    name = "".join(c for c in name if c.isprintable()) or "evidence.pdf"
    doc = EvidenceDocument(transaction_id=tid, filename=name, file_data=bytes(data),
                           mime_type="application/pdf", size=len(data), text_content=json.dumps(pages))
    db.add(doc)
    db.flush()
    audit(db, mid, "evidence.uploaded", "document", doc.id)
    db.commit()
    return document_out(doc)


@router.get("/transactions/{tid}/evidence")
def list_evidence(tid: int, db: DB, mid: MID):
    evidence.owned_transaction(db, mid, tid)
    return {"items": [document_out(d) for d in evidence.documents(db, tid)],
            "facts": [{"id": f.id, "document_id": f.document_id, "fact_type": f.fact_type,
                       "page": f.page, "excerpt": f.excerpt, "confidence": f.confidence}
                      for f in evidence.facts(db, tid)]}


@router.get("/evidence/{did}/download")
def download(did: int, db: DB, mid: MID):
    doc = db.scalar(select(EvidenceDocument).join(Transaction).where(EvidenceDocument.id == did, Transaction.merchant_id == mid))
    if not doc:
        raise HTTPException(404, "Document not found.")
    return Response(doc.file_data, media_type="application/pdf", headers={
        "Content-Disposition": "attachment; filename*=UTF-8''" + quote(doc.filename, safe=""),
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@router.post("/transactions/{tid}/analyze")
def analyze(tid: int, db: DB, mid: MID):
    tx = evidence.owned_transaction(db, mid, tid, lock=True)
    docs = evidence.documents(db, tid)
    if not docs:
        raise HTTPException(409, "Upload a text PDF before analysis.")
    results = []
    pages = [{**p, "document_id": doc.id} for doc in docs for p in evidence.document_pages(doc)]
    if sum(len(p["text"]) for p in pages) > 100_000:
        raise HTTPException(422, "Combined evidence exceeds 100,000 text characters. Use shorter documents.")
    candidates = gemini.extract(pages)
    for doc in docs:
        results.extend(evidence.checked_facts(doc, candidates))
    # Atomic replacement: provider failure leaves the previous analysis untouched.
    db.execute(delete(ExtractedFact).where(ExtractedFact.document_id.in_([d.id for d in docs])))
    db.add_all(results)
    audit(db, mid, "evidence.analyzed", "transaction", tid, {"accepted_facts": len(results)})
    db.commit()
    return {**evidence.readiness(db, tx), "accepted_facts": len(results)}


@router.get("/transactions/{tid}/readiness")
def readiness(tid: int, db: DB, mid: MID):
    return evidence.readiness(db, evidence.owned_transaction(db, mid, tid))


def owned_dispute(db, mid, did, lock=False):
    query = select(Dispute).join(Transaction).where(Dispute.id == did, Transaction.merchant_id == mid)
    dispute = db.scalar(query.with_for_update() if lock else query)
    if not dispute:
        raise HTTPException(404, "Dispute not found.")
    return dispute


def latest_response(db, did):
    return db.scalar(select(DisputeResponse).where(DisputeResponse.dispute_id == did).order_by(DisputeResponse.id.desc()))


def validate_citations(db, dispute, response):
    docs = {d.id: {p['page']: p['text'] for p in evidence.document_pages(d)} for d in evidence.documents(db, dispute.transaction_id)}
    for c in response.citations:
        text = docs.get(c.get('document_id'), {}).get(c.get('page'), '')
        excerpt = c.get('excerpt')
        if not isinstance(excerpt, str) or not excerpt.strip() or excerpt not in text:
            raise HTTPException(409, 'A source quotation is no longer valid. Generate a fresh draft.')


def response_out(response):
    if not response:
        return None
    return {"id": response.id, "draft_text": response.draft_text, "citations": response.citations,
            "status": response.status, "approved_at": response.approved_at}


@router.get("/disputes")
def list_disputes(db: DB, mid: MID):
    disputes = db.scalars(select(Dispute).join(Transaction).where(Transaction.merchant_id == mid).order_by(Dispute.id.desc())).all()
    return {"items": [{"id": d.id, "transaction_id": d.transaction_id, "paypal_dispute_id": d.paypal_dispute_id,
                       "reason": d.reason, "status": d.status, "amount": str(d.amount),
                       "response_due_at": d.response_due_at, "is_fixture": d.is_fixture,
                       "response": response_out(latest_response(db, d.id))} for d in disputes]}


@router.post("/disputes/sync")
def sync_disputes(db: DB, mid: MID):
    db.scalar(select(Merchant).where(Merchant.id == mid).with_for_update())
    txs = db.scalars(select(Transaction).where(Transaction.merchant_id == mid)).all()
    added = 0
    if get_settings().dispute_source == "fixture":
        for tx in txs:
            ident = f"SIMULATED-{mid}-{tx.id}"
            if db.scalar(select(Dispute).where(Dispute.transaction_id == tx.id, Dispute.is_fixture.is_(True))):
                continue
            db.add(Dispute(transaction_id=tx.id, paypal_dispute_id=ident, reason="SERVICE_NOT_RECEIVED",
                           status="WAITING_FOR_SELLER_RESPONSE", amount=tx.amount, is_fixture=True,
                           response_due_at=datetime.now(timezone.utc) + timedelta(days=7), raw={"source": "simulated"}))
            added += 1
    else:
        client = next_client = None
        try:
            next_client = get_paypal()
            client = next(next_client)
            token = None
            for _ in range(10):
                page = client.list_disputes(next_page_token=token)
                for item in page.get("items", []):
                    remote = client.get_dispute(item["dispute_id"])
                    ids = {t.get("seller_transaction_id") for t in remote.get("disputed_transactions", [])}
                    tx = next((t for t in txs if t.paypal_capture_id and t.paypal_capture_id in ids), None)
                    if not tx:
                        continue  # Never expose unmatched disputes from a shared Sandbox account.
                    d = db.scalar(select(Dispute).where(Dispute.paypal_dispute_id == remote["dispute_id"]))
                    if d and d.transaction_id != tx.id:
                        continue
                    if not d:
                        d = Dispute(transaction_id=tx.id, paypal_dispute_id=remote["dispute_id"], amount=tx.amount, is_fixture=False)
                        db.add(d)
                        added += 1
                    d.reason, d.status, d.raw = remote.get("reason", "UNKNOWN"), remote.get("status", "UNKNOWN"), remote
                    due = remote.get("seller_response_due_date")
                    d.response_due_at = datetime.fromisoformat(due.replace("Z", "+00:00")) if due else None
                # Follow only the token, never an upstream-controlled URL.
                from urllib.parse import urlsplit, parse_qs
                link = next((l.get("href", "") for l in page.get("links", []) if l.get("rel") == "next"), "")
                token = parse_qs(urlsplit(link).query).get("next_page_token", [None])[0]
                if not token:
                    break
        except (PayPalError, KeyError, TypeError, ValueError):
            raise HTTPException(502, "PayPal dispute sync failed; retry later.") from None
        finally:
            if next_client:
                next_client.close()
    audit(db, mid, "disputes.synced", "merchant", mid, {"added": added})
    db.commit()
    return {"added": added, "source": get_settings().dispute_source}


@router.post("/disputes/{did}/draft")
def draft(did: int, db: DB, mid: MID):
    d = owned_dispute(db, mid, did, lock=True)
    fs = evidence.facts(db, d.transaction_id)
    citations = [{"document_id": f.document_id, "page": f.page, "excerpt": f.excerpt,
                  "fact_type": f.fact_type} for f in fs]
    lines = ["SIMULATED DISPUTE — review only" if d.is_fixture else "Dispute response — merchant review required", ""]
    if not citations:
        lines.append("Insufficient evidence: upload and analyze documents before making claims about delivery or acceptance.")
    for number, c in enumerate(citations, 1):
        label = "Concern requiring review" if c["fact_type"].startswith("concern_") else "Document states"
        lines.append(f'{label}: "{c["excerpt"]}" [{number}: document {c["document_id"]}, page {c["page"]}]')
    lines.extend(["", "These quotations are evidence supplied by the merchant. Review relevance, authenticity, and any contradictions before using this response."])
    response = DisputeResponse(dispute_id=did, draft_text="\n\n".join(lines), citations=citations, status="draft")
    db.add(response)
    audit(db, mid, "dispute.drafted", "dispute", did)
    db.commit()
    return response_out(response)


class EditResponse(BaseModel):
    draft_text: str = Field(min_length=1, max_length=50_000)


@router.put("/disputes/{did}/response")
def edit_response(did: int, body: EditResponse, db: DB, mid: MID):
    owned_dispute(db, mid, did, lock=True)
    response = latest_response(db, did)
    if not response:
        raise HTTPException(409, "Generate a draft first.")
    response.draft_text, response.status, response.approved_at = body.draft_text, "draft", None
    audit(db, mid, "dispute.edited", "dispute", did)
    db.commit()
    return response_out(response)


@router.post("/disputes/{did}/approve")
def approve(did: int, db: DB, mid: MID):
    dispute = owned_dispute(db, mid, did, lock=True)
    response = latest_response(db, did)
    if not response:
        raise HTTPException(409, "Generate a draft first.")
    validate_citations(db, dispute, response)
    if response.status == "draft":
        response.status, response.approved_at = "approved", datetime.now(timezone.utc)
        audit(db, mid, "dispute.approved", "dispute", did, {"response_id": response.id, "text": response.draft_text})
        db.commit()
    return response_out(response)


@router.get("/disputes/{did}/export")
def export(did: int, db: DB, mid: MID):
    d = owned_dispute(db, mid, did, lock=True)
    response = latest_response(db, did)
    if not response or response.status not in ("approved", "exported"):
        raise HTTPException(409, "Approve the latest response before exporting.")
    validate_citations(db, d, response)
    text = response.draft_text + "\n\n## Source quotations\n"
    for c in response.citations:
        text += f'\nDocument {c["document_id"]}, page {c["page"]}: {c["excerpt"]}\n'
    if d.is_fixture:
        text = "# SIMULATED — not submitted to PayPal\n\n" + text
    response.status = "exported"
    audit(db, mid, "dispute.exported", "dispute", did)
    db.commit()
    return Response(text, media_type="text/markdown", headers={"Content-Disposition": f'attachment; filename="dispute-{did}.md"', "Cache-Control": "no-store"})


@router.get("/dashboard/summary")
def dashboard(db: DB, mid: MID):
    txs = db.scalars(select(Transaction).where(Transaction.merchant_id == mid)).all()
    scores = [{"transaction_id": t.id, "description": t.description, **evidence.readiness(db, t)} for t in txs]
    disputes = db.scalars(select(Dispute).join(Transaction).where(Transaction.merchant_id == mid)).all()
    totals = {}
    for tx in txs:
        if tx.status == "VERIFIED":
            totals[tx.currency] = totals.get(tx.currency, 0) + tx.amount
    return {"transactions": len(txs), "verified": sum(t.status == "VERIFIED" for t in txs),
            "verified_totals": {k: str(v) for k, v in totals.items()},
            "open_disputes": sum(d.status not in ("RESOLVED", "CLOSED") for d in disputes),
            "simulated_disputes": sum(d.is_fixture for d in disputes), "readiness": scores}

