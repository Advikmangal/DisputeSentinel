"""Merchant-owned evidence, deterministic readiness and reviewed dispute exports."""
import json
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from fastapi import APIRouter, File, UploadFile, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select, delete
from app.config import get_settings
from app.models import Transaction, EvidenceDocument, ExtractedFact, ReadinessScore, Dispute, DisputeResponse, AuditLog
from app.routers.payments import DB, MerchantID, PayPal
from app.services.evidence import extract_pages, analyze_documents, CATEGORIES
from app.services.paypal import PayPalError

router = APIRouter(prefix='/api', tags=['evidence and disputes'])


def transaction(db, merchant, id):
    tx = db.scalar(select(Transaction).where(Transaction.id == id, Transaction.merchant_id == merchant).with_for_update())
    if tx is None:
        raise HTTPException(404, 'Transaction not found.')
    return tx


def metadata(doc):
    return {key: getattr(doc, key) for key in ('id', 'transaction_id', 'filename', 'mime_type', 'size', 'uploaded_at')}


def score_out(row):
    return {key: getattr(row, key) for key in ('id', 'transaction_id', 'score', 'breakdown', 'missing_items', 'computed_at')}


@router.post('/transactions/{id}/evidence', status_code=201)
def upload(id: int, merchant_id: MerchantID, db: DB, file: UploadFile = File(...)):
    transaction(db, merchant_id, id)
    if len(db.scalars(select(EvidenceDocument.id).where(EvidenceDocument.transaction_id == id)).all()) >= 10:
        raise HTTPException(409, 'Maximum 10 evidence documents per transaction.')
    data = file.file.read(10_000_001)
    if len(data) > 10_000_000:
        raise HTTPException(413, 'PDF must be at most 10 MB.')
    pages = extract_pages(data)
    name = (file.filename or 'evidence.pdf').replace('\\', '/').split('/')[-1][:200]
    doc = EvidenceDocument(transaction_id=id, filename=name, mime_type='application/pdf', size=len(data), file_data=data, text_content=json.dumps(pages))
    db.add(doc)
    # New evidence makes the old score stale; retain cited facts for existing responses.
    db.execute(delete(ReadinessScore).where(ReadinessScore.transaction_id == id))
    db.commit()
    return metadata(doc)


@router.get('/transactions/{id}/evidence')
def evidence(id: int, merchant_id: MerchantID, db: DB):
    transaction(db, merchant_id, id)
    return {'items': [metadata(d) for d in db.scalars(select(EvidenceDocument).where(EvidenceDocument.transaction_id == id).order_by(EvidenceDocument.id))]}


@router.get('/transactions/{id}/evidence/{document_id}/download')
def download(id: int, document_id: int, merchant_id: MerchantID, db: DB):
    transaction(db, merchant_id, id)
    doc = db.scalar(select(EvidenceDocument).where(EvidenceDocument.id == document_id, EvidenceDocument.transaction_id == id))
    if doc is None:
        raise HTTPException(404, 'Evidence not found.')
    return Response(doc.file_data, media_type='application/pdf', headers={'Content-Disposition': f'attachment; filename="evidence-{document_id}.pdf"', 'X-Content-Type-Options': 'nosniff'})


@router.post('/transactions/{id}/analyze')
def analyze(id: int, merchant_id: MerchantID, db: DB):
    tx = transaction(db, merchant_id, id)
    docs = db.scalars(select(EvidenceDocument).where(EvidenceDocument.transaction_id == id).order_by(EvidenceDocument.id)).all()
    if not docs:
        raise HTTPException(409, 'Upload evidence first.')
    facts = analyze_documents(docs)
    doc_ids = [d.id for d in docs]
    db.execute(delete(ExtractedFact).where(ExtractedFact.document_id.in_(doc_ids)))
    records = []
    for fact in facts:
        record = ExtractedFact(**fact.model_dump(), value=fact.excerpt)
        db.add(record)
        records.append(record)
    present = {f.fact_type for f in facts if f.confidence >= .7}
    # Payment match needs a server-verified capture ID quoted in the evidence.
    if tx.status != 'VERIFIED' or not tx.paypal_capture_id or not any(tx.paypal_capture_id in f.excerpt and f.fact_type == 'proof_of_payment_match' for f in facts):
        present.discard('proof_of_payment_match')
    breakdown = [{'item': k, 'status': 'present' if k in present else 'missing', 'points': 20 if k in present else 0, 'max_points': 20} for k in CATEGORIES]
    db.execute(delete(ReadinessScore).where(ReadinessScore.transaction_id == id))
    score = ReadinessScore(transaction_id=id, score=sum(x['points'] for x in breakdown), breakdown=breakdown, missing_items=[k for k in CATEGORIES if k not in present])
    db.add(score)
    db.commit()
    return {'transaction_id': id, 'facts': [{'id': f.id, 'document_id': f.document_id, 'page': f.page, 'fact_type': f.fact_type, 'excerpt': f.excerpt, 'confidence': f.confidence} for f in records], 'readiness': score_out(score)}


@router.get('/transactions/{id}/readiness')
def readiness(id: int, merchant_id: MerchantID, db: DB):
    transaction(db, merchant_id, id)
    row = db.scalar(select(ReadinessScore).where(ReadinessScore.transaction_id == id).order_by(ReadinessScore.id.desc()))
    return score_out(row) if row else None


def dispute_out(row):
    return {key: getattr(row, key) for key in ('id', 'transaction_id', 'paypal_dispute_id', 'reason', 'status', 'amount', 'response_due_at', 'is_fixture')}


def response_out(row):
    return {key: getattr(row, key) for key in ('id', 'dispute_id', 'draft_text', 'citations', 'status', 'approved_at', 'submitted_at')}


def owned_dispute(db, merchant, id):
    d = db.scalar(select(Dispute).join(Transaction).where(Dispute.id == id, Transaction.merchant_id == merchant).with_for_update())
    if d is None:
        raise HTTPException(404, 'Dispute not found.')
    return d


def current_response(db, id):
    return db.scalar(select(DisputeResponse).where(DisputeResponse.dispute_id == id).order_by(DisputeResponse.id.desc()))


@router.get('/disputes')
def disputes(merchant_id: MerchantID, db: DB):
    rows = db.scalars(select(Dispute).join(Transaction).where(Transaction.merchant_id == merchant_id).order_by(Dispute.id.desc())).all()
    return {'items': [{**dispute_out(d), 'response': response_out(r) if (r := current_response(db, d.id)) else None} for d in rows]}


class Sync(BaseModel):
    transaction_id: int = Field(gt=0)


@router.post('/disputes/sync')
def sync(body: Sync, merchant_id: MerchantID, db: DB, paypal: PayPal):
    tx = transaction(db, merchant_id, body.transaction_id)
    if get_settings().dispute_source == 'fixture':
        remote_id = f'FIXTURE-{merchant_id}-{tx.id}'
        row = db.scalar(select(Dispute).where(Dispute.paypal_dispute_id == remote_id))
        if row is None:
            row = Dispute(transaction_id=tx.id, paypal_dispute_id=remote_id, reason='MERCHANDISE_OR_SERVICE_NOT_RECEIVED', status='WAITING_FOR_SELLER_RESPONSE', amount=tx.amount, is_fixture=True, raw={'source': 'simulated'})
            db.add(row)
        db.commit()
        return {'items': [dispute_out(row)], 'source': 'fixture'}
    if not tx.paypal_capture_id:
        raise HTTPException(409, 'A verified capture is needed to match PayPal disputes.')
    try:
        result = paypal.list_disputes(page_size=50)
        rows = []
        # One page per explicit sync; do not claim a complete account-wide import.
        for item in result.get('items', []):
            remote = paypal.get_dispute(item['dispute_id'])
            matches = [t for t in remote.get('disputed_transactions', []) if t.get('seller_transaction_id') == tx.paypal_capture_id]
            if not matches:
                continue
            money = remote['dispute_amount']
            if money['currency_code'] != tx.currency or Decimal(money['value']) != tx.amount:
                continue
            row = db.scalar(select(Dispute).where(Dispute.paypal_dispute_id == remote['dispute_id']))
            if row and row.transaction_id != tx.id:
                continue
            if row is None:
                row = Dispute(transaction_id=tx.id, paypal_dispute_id=remote['dispute_id'], amount=tx.amount, is_fixture=False)
                db.add(row)
            row.reason, row.status, row.raw = remote['reason'], remote['status'], remote
            rows.append(row)
        db.commit()
    except (PayPalError, KeyError, TypeError, ValueError):
        db.rollback()
        raise HTTPException(502, 'Dispute sync failed; retry later.') from None
    return {'items': [dispute_out(d) for d in rows], 'source': 'paypal', 'scope': 'first_page'}


def validate_citations(db, dispute, citations):
    docs = {d.id: json.loads(d.text_content) for d in db.scalars(select(EvidenceDocument).where(EvidenceDocument.transaction_id == dispute.transaction_id))}
    for c in citations:
        pages = docs.get(c.get('document_id'), [])
        page, excerpt = c.get('page'), c.get('excerpt')
        if not isinstance(page, int) or not 1 <= page <= len(pages) or not isinstance(excerpt, str) or not excerpt.strip() or excerpt not in pages[page-1]:
            raise HTTPException(422, 'Citation must quote an exact excerpt from this transaction’s evidence.')


@router.post('/disputes/{id}/draft')
def draft(id: int, merchant_id: MerchantID, db: DB):
    dispute = owned_dispute(db, merchant_id, id)
    response = current_response(db, id)
    if response:
        return {'dispute': dispute_out(dispute), 'response': response_out(response)}
    facts = db.scalars(select(ExtractedFact).join(EvidenceDocument).where(EvidenceDocument.transaction_id == dispute.transaction_id).order_by(ExtractedFact.id)).all()
    if not facts:
        raise HTTPException(409, 'Analyze evidence before drafting a response.')
    citations = [{'document_id': f.document_id, 'page': f.page, 'excerpt': f.excerpt} for f in facts]
    validate_citations(db, dispute, citations)
    draft_text = 'Evidence supplied by the merchant (document claims, not independently verified):\n\n' + '\n\n'.join(f'[{i}] {c["excerpt"]}' for i, c in enumerate(citations, 1))
    response = DisputeResponse(dispute_id=id, draft_text=draft_text, citations=citations, status='draft')
    db.add(response)
    db.commit()
    return {'dispute': dispute_out(dispute), 'response': response_out(response)}


class Edit(BaseModel):
    model_config = ConfigDict(extra='forbid')
    draft_text: str = Field(min_length=1, max_length=30000)
    citations: list[dict] = Field(max_length=100)


@router.put('/disputes/{id}/response')
def edit(id: int, body: Edit, merchant_id: MerchantID, db: DB):
    dispute = owned_dispute(db, merchant_id, id)
    response = current_response(db, id)
    if response is None or response.status in ('exported', 'submitted'):
        raise HTTPException(409, 'No editable response.')
    validate_citations(db, dispute, body.citations)
    response.draft_text, response.citations = body.draft_text, body.citations
    response.status, response.approved_at = 'draft', None
    db.commit()
    return {'response': response_out(response), 'dispute': dispute_out(dispute)}


@router.post('/disputes/{id}/approve')
def approve(id: int, merchant_id: MerchantID, db: DB):
    dispute = owned_dispute(db, merchant_id, id)
    response = current_response(db, id)
    if response is None or response.status not in ('draft', 'approved'):
        raise HTTPException(409, 'No reviewable draft.')
    validate_citations(db, dispute, response.citations)
    if response.status == 'draft':
        response.status, response.approved_at = 'approved', datetime.now(timezone.utc)
        db.add(AuditLog(merchant_id=merchant_id, action='dispute_response.approved', entity_type='dispute_response', entity_id=response.id, detail={'dispute_id': id, 'is_fixture': dispute.is_fixture}))
        db.commit()
    return {'response': response_out(response), 'dispute': dispute_out(dispute)}


@router.post('/disputes/{id}/submit')
def export(id: int, merchant_id: MerchantID, db: DB):
    dispute = owned_dispute(db, merchant_id, id)
    response = current_response(db, id)
    if response is None or response.status not in ('approved', 'exported'):
        raise HTTPException(409, 'Review and approve the current response before exporting.')
    validate_citations(db, dispute, response.citations)
    response.status = 'exported'
    db.commit()
    label = 'Simulated dispute response' if dispute.is_fixture else 'Dispute response — manual submission required'
    content = '# ' + label + '\n\n' + response.draft_text + '\n\n' + '\n'.join(f'[{i}] Document {c["document_id"]}, page {c["page"]}: {c["excerpt"]}' for i, c in enumerate(response.citations, 1))
    return {'response': response_out(response), 'dispute': dispute_out(dispute), 'delivery': {'mode': 'export', 'filename': f'dispute-{id}.md', 'format': 'markdown', 'content': content}}


@router.get('/dashboard/summary')
def summary(merchant_id: MerchantID, db: DB):
    txs = db.scalars(select(Transaction).where(Transaction.merchant_id == merchant_id)).all()
    totals = defaultdict(Decimal)
    for tx in txs:
        if tx.status == 'VERIFIED':
            totals[tx.currency] += tx.amount
    return {'transaction_count': len(txs), 'verified_transaction_count': sum(t.status == 'VERIFIED' for t in txs), 'verified_amount_by_currency': {k: format(v, '.2f') for k, v in totals.items()}}
