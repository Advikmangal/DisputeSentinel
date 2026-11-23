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


