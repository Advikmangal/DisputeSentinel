"""Service acceptance checks that do not require an HTTP event loop."""
import json
from decimal import Decimal
from types import SimpleNamespace
import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session
from app.db import Base
from app.models import Merchant, Transaction, EvidenceDocument, ExtractedFact, AuditLog
from app.routers import workspace
from app.services import evidence, gemini
from app.tests.test_workspace import pdf_bytes, candidate


@pytest.fixture
def db():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        session.add(Merchant(id=1, email='test@example.invalid', password_hash='not-a-login'))
        session.add(Transaction(id=1, merchant_id=1, paypal_order_id='TEST-1', amount=Decimal('1'), currency='USD', status='CREATED', description='Synthetic test'))
        session.commit()
        yield session
    engine.dispose()


def document(db, text=None):
    data = pdf_bytes(text) if text else pdf_bytes()
    pages = evidence.extract_pages(data)
    doc = EvidenceDocument(transaction_id=1, filename='synthetic.pdf', size=len(data), mime_type='application/pdf', file_data=data, text_content=json.dumps(pages))
    db.add(doc); db.commit()
    return doc


def test_real_pdf_and_source_validation(db):
    doc = document(db)
    fabricated = candidate().model_copy(update={'excerpt': 'This never happened.'})
    wrong_page = candidate().model_copy(update={'page': 2})
    wrong_doc = candidate().model_copy(update={'document_id': 9})
    assert len(evidence.checked_facts(doc, [candidate(), candidate(), fabricated, wrong_page, wrong_doc])) == 1


def test_private_download(db):
    doc = document(db)
    assert workspace.download(doc.id, db, 1).body == doc.file_data
    with pytest.raises(HTTPException) as error:
        workspace.download(doc.id, db, 2)
    assert error.value.status_code == 404


def test_complete_review_lifecycle(db, monkeypatch):
    document(db)
    monkeypatch.setattr(gemini, 'extract', lambda pages: [candidate()])
    monkeypatch.setattr(workspace, 'get_settings', lambda: SimpleNamespace(dispute_source='fixture'))
    assert workspace.analyze(1, db, 1)['score'] == 30
    assert workspace.sync_disputes(db, 1)['added'] == 1
    assert workspace.sync_disputes(db, 1)['added'] == 0
    case = workspace.list_disputes(db, 1)['items'][0]['id']
    assert workspace.draft(case, db, 1)['citations']
    with pytest.raises(HTTPException):
        workspace.export(case, db, 1)
    assert workspace.approve(case, db, 1)['status'] == 'approved'
    assert b'SIMULATED' in workspace.export(case, db, 1).body
    workspace.edit_response(case, workspace.EditResponse(draft_text='Reviewed change'), db, 1)
    with pytest.raises(HTTPException):
        workspace.export(case, db, 1)
    assert db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == 'dispute.approved')) == 1


def test_analysis_failure_keeps_facts(db, monkeypatch):
    doc = document(db)
    db.add_all(evidence.checked_facts(doc, [candidate()])); db.commit()
    def fail(pages):
        raise HTTPException(502, 'Unavailable')
    monkeypatch.setattr(gemini, 'extract', fail)
    with pytest.raises(HTTPException):
        workspace.analyze(1, db, 1)
    assert len(evidence.facts(db, 1)) == 1


def test_coverage_empty_full_and_conflicting(db):
    tx = db.get(Transaction, 1)
    assert evidence.readiness(db, tx)['score'] == 0
    doc = document(db)
    for kind in ['delivery', 'communication', 'agreement', 'access']:
        db.add(ExtractedFact(document_id=doc.id, fact_type=kind, page=1, excerpt='quotation', value='quotation', confidence=.95))
    tx.status = 'VERIFIED'; db.commit()
    assert evidence.readiness(db, tx)['score'] == 100
    db.add(ExtractedFact(document_id=doc.id, fact_type='concern_delivery', page=1, excerpt='concern', value='concern', confidence=.95)); db.commit()
    assert evidence.readiness(db, tx)['score'] == 70
    assert evidence.readiness(db, tx)['breakdown'][0]['status'] == 'review'


def test_legacy_page_format_survives_upgrade(db):
    doc = document(db)
    doc.text_content = json.dumps(['The project files were delivered on November 3, 2026.'])
    db.commit()
    assert len(evidence.checked_facts(doc, [candidate()])) == 1


def test_bad_pdf():
    with pytest.raises(HTTPException):
        evidence.extract_pages(b'not pdf')


def test_gemini_schema_request_and_retry(monkeypatch):
    from app.config import Settings
    monkeypatch.setattr(gemini, 'get_settings', lambda: Settings(_env_file=None, gemini_api_key='synthetic', gemini_model='gemini-test'))
    calls = []
    def handler(request):
        body = json.loads(request.content)
        assert body['generationConfig']['responseJsonSchema']
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429)
        return httpx.Response(200, json={'candidates': [{'content': {'parts': [{'text': json.dumps({'facts': [candidate().model_dump()]})}]}}]})
    original = httpx.Client
    monkeypatch.setattr(gemini.httpx, 'Client', lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(gemini.time, 'sleep', lambda _: None)
    assert len(gemini.extract([{'document_id': 1, 'page': 1, 'text': 'Synthetic text'}])) == 1
    assert len(calls) == 2
