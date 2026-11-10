import io
import json
from unittest.mock import Mock
import pytest
from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from pypdf import PdfWriter
from app.tests.test_payments import api, create
from app.models import WebhookEvent, EvidenceDocument, ExtractedFact, AuditLog, Transaction
from app.services.evidence import Fact
from app.routers import workflows
from app.config import get_settings
from app.main import app


def test_payment_config_never_exposes_secret(api, monkeypatch):
    client, _, _ = api
    monkeypatch.setenv('PAYPAL_CLIENT_ID', 'public-sandbox-id')
    monkeypatch.setenv('PAYPAL_CLIENT_SECRET', 'private-secret')
    get_settings.cache_clear()
    response = client.get('/api/payments/config')
    assert response.status_code == 200
    assert response.json() == {'client_id': 'public-sandbox-id', 'currency': 'USD', 'environment': 'sandbox'}
    assert 'private-secret' not in response.text


def test_readiness_reports_database_failure(api, monkeypatch):
    client, _, _ = api
    monkeypatch.setattr('app.main.get_engine', Mock(side_effect=RuntimeError('private-db-url')))
    response = client.get('/ready')
    assert response.status_code == 503
    assert 'private-db-url' not in response.text
    assert client.get('/health').status_code == 200


HEADERS = {f'paypal-{key}': 'synthetic' for key in ['auth-algo', 'cert-url', 'transmission-id', 'transmission-sig', 'transmission-time']}
EVENT = {'id': 'WH-1', 'event_type': 'PAYMENT.CAPTURE.COMPLETED', 'resource': {'id': 'CAPTURE-1', 'supplementary_data': {'related_ids': {'order_id': 'ORDER-1'}}}}


def setup_webhook(api, monkeypatch, valid=True):
    client, state, engine = api
    create(client)
    monkeypatch.setenv('PAYPAL_WEBHOOK_ID', 'test-webhook')
    get_settings.cache_clear()
    from app.routers.payments import get_paypal
    paypal = app.dependency_overrides[get_paypal]()
    original = paypal._request
    def request(method, path, **kwargs):
        if path.endswith('verify-webhook-signature'):
            assert json.loads(kwargs['content'])['webhook_event'] == EVENT
            return {'verification_status': 'SUCCESS' if valid else 'FAILURE'}
        return original(method, path, **kwargs)
    monkeypatch.setattr(paypal, '_request', request)
    del client.headers['Authorization']
    return client, state, engine


def test_webhook_reconciles_without_capture_and_deduplicates(api, monkeypatch):
    client, state, engine = setup_webhook(api, monkeypatch)
    state['status'] = 'COMPLETED'
    assert client.post('/api/webhooks/paypal', json=EVENT, headers=HEADERS).json() == {'status': 'ok', 'duplicate': False}
    assert client.post('/api/webhooks/paypal', json=EVENT, headers=HEADERS).json()['duplicate']
    assert not any(r.url.path.endswith('/capture') and r.method == 'POST' for r in state['calls'])
    with Session(engine) as db:
        assert db.get(Transaction, 1).status == 'VERIFIED'
        assert db.scalar(select(func.count()).select_from(WebhookEvent)) == 1


def test_failed_webhook_is_retryable(api, monkeypatch):
    client, state, engine = setup_webhook(api, monkeypatch)
    assert client.post('/api/webhooks/paypal', json=EVENT, headers=HEADERS).status_code == 502
    state['status'] = 'COMPLETED'
    assert client.post('/api/webhooks/paypal', json=EVENT, headers=HEADERS).status_code == 200


def test_invalid_signature_cannot_mutate(api, monkeypatch):
    client, state, engine = setup_webhook(api, monkeypatch, valid=False)
    assert client.post('/api/webhooks/paypal', json=EVENT, headers=HEADERS).status_code == 400
    with Session(engine) as db:
        assert db.get(Transaction, 1).status == 'CREATED'
        assert db.scalar(select(func.count()).select_from(WebhookEvent)) == 0


def test_pdf_validation_and_ownership(api):
    client, _, _ = api
    create(client)
    assert client.post('/api/transactions/1/evidence', files={'file': ('bad.pdf', b'not a pdf', 'application/pdf')}).status_code == 415
    assert client.post('/api/transactions/999/evidence', files={'file': ('bad.pdf', b'x')}).status_code == 404
    writer = PdfWriter(); writer.add_blank_page(width=100, height=100)
    data = io.BytesIO(); writer.write(data)
    assert client.post('/api/transactions/1/evidence', files={'file': ('blank.pdf', data.getvalue())}).status_code == 422


def test_evidence_draft_approval_export_lifecycle(api, monkeypatch):
    client, state, engine = api
    create(client)
    # Upload path uses actual bounded storage; extraction mocked to isolate model workflow.
    monkeypatch.setattr(workflows, 'extract_pages', lambda data: ['The project was delivered.'])
    uploaded = client.post('/api/transactions/1/evidence', files={'file': ('delivery.pdf', b'%PDF-test', 'application/pdf')})
    assert uploaded.status_code == 201, uploaded.text
    assert 'file_data' not in uploaded.text
    monkeypatch.setattr(workflows, 'analyze_documents', lambda docs: [Fact(document_id=docs[0].id, page=1, fact_type='proof_of_delivery', excerpt='The project was delivered.', confidence=.9)])
    result = client.post('/api/transactions/1/analyze')
    assert result.status_code == 200, result.text
    assert result.json()['readiness']['score'] == 20
    first = client.post('/api/disputes/sync', json={'transaction_id': 1}).json()['items'][0]
    assert first['is_fixture']
    assert client.post('/api/disputes/sync', json={'transaction_id': 1}).json()['items'][0]['id'] == first['id']
    id = first['id']
    draft = client.post(f'/api/disputes/{id}/draft').json()['response']
    assert client.post(f'/api/disputes/{id}/submit').status_code == 409
    assert client.post(f'/api/disputes/{id}/approve').status_code == 200
    edited = {**{k: draft[k] for k in ('draft_text', 'citations')}, 'draft_text': 'Merchant-reviewed response.'}
    assert client.put(f'/api/disputes/{id}/response', json=edited).json()['response']['status'] == 'draft'
    assert client.post(f'/api/disputes/{id}/submit').status_code == 409
    client.post(f'/api/disputes/{id}/approve')
    exported = client.post(f'/api/disputes/{id}/submit')
    assert exported.json()['delivery']['mode'] == 'export'
    assert 'Simulated' in exported.json()['delivery']['content']
    assert exported.json()['response']['submitted_at'] is None
    assert client.post(f'/api/disputes/{id}/submit').json() == exported.json()
    assert client.put(f'/api/disputes/{id}/response', json=edited).status_code == 409
    assert not any('/disputes' in str(r.url) for r in state['calls'])
    # Foreign merchant cannot read evidence, analysis, or response.
    login = client.post('/api/auth/login', json={'email': 'two@example.invalid', 'password': state['password']})
    client.headers['Authorization'] = 'Bearer ' + login.json()['access_token']
    assert client.get('/api/transactions/1/evidence').status_code == 404
    assert client.post(f'/api/disputes/{id}/approve').status_code == 404
    assert client.get('/api/disputes').json()['items'] == []


def test_gemini_rejects_invented_citations(monkeypatch):
    from app.services.evidence import analyze_documents
    from types import SimpleNamespace
    monkeypatch.setenv('GEMINI_API_KEY', 'synthetic-key')
    monkeypatch.setenv('GEMINI_MODEL', 'gemini-test')
    get_settings.cache_clear()
    facts = [{'document_id': 1, 'page': 1, 'fact_type': 'proof_of_delivery', 'excerpt': quote, 'confidence': .9} for quote in ['Real quotation.', 'Invented statement.']]
    response = Mock(); response.json.return_value = {'candidates': [{'content': {'parts': [{'text': json.dumps({'facts': facts})}]}}]}
    context = Mock(); context.__enter__ = Mock(return_value=Mock(post=Mock(return_value=response))); context.__exit__ = Mock(return_value=False)
    monkeypatch.setattr('app.services.evidence.httpx.Client', Mock(return_value=context))
    result = analyze_documents([SimpleNamespace(id=1, text_content=json.dumps(['Real quotation.']))])
    assert len(result) == 1 and result[0].excerpt == 'Real quotation.'


def test_real_pdf_text_extraction():
    from pypdf.generic import DecodedStreamObject, NameObject, DictionaryObject
    from app.services.evidence import extract_pages
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
    stream = DecodedStreamObject(); stream.set_data(b'BT /F1 12 Tf 20 200 Td (Delivered project files.) Tj ET')
    page[NameObject('/Contents')] = writer._add_object(stream)
    output = io.BytesIO(); writer.write(output)
    assert 'Delivered project files.' in extract_pages(output.getvalue())[0]
