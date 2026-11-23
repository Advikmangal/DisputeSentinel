import io
import json
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.models import AuditLog, EvidenceDocument, ExtractedFact
from app.services.gemini import Fact
from app.tests.test_payments import api, create, capture


def pdf_bytes(text="The project files were delivered on November 3, 2026."):
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = writer._add_object(DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')}))
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
    stream = DecodedStreamObject()
    stream.set_data(f'BT /F1 12 Tf 50 700 Td ({text}) Tj ET'.encode())
    page[NameObject('/Contents')] = writer._add_object(stream)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def upload(client, tid, data=None):
    return client.post(f'/api/transactions/{tid}/evidence?filename=delivery.pdf', content=data or pdf_bytes(), headers={'Content-Type': 'application/pdf'})


def candidate(**kwargs):
    return Fact(document_id=1, fact_type='delivery', page=1, excerpt='The project files were delivered on November 3, 2026.', confidence=.95, supports_claim=True, **kwargs)


def test_evidence_to_approved_export_and_edit_invalidates_approval(api, monkeypatch):
    client, state, engine = api
    tid = create(client).json()['transaction']['id']
    capture(client)
    r = upload(client, tid)
    assert r.status_code == 201, r.text
    did = r.json()['id']
    assert client.get(f'/api/evidence/{did}/download').content == pdf_bytes()
    monkeypatch.setattr('app.services.gemini.extract', lambda pages: [candidate()])
    result = client.post(f'/api/transactions/{tid}/analyze')
    assert result.status_code == 200, result.text
    assert result.json()['score'] == 45
    assert result.json()['accepted_facts'] == 1
    assert client.post('/api/disputes/sync').json()['added'] == 1
    assert client.post('/api/disputes/sync').json()['added'] == 0
    dispute = client.get('/api/disputes').json()['items'][0]
    ident = dispute['id']
    assert dispute['is_fixture']
    drafted = client.post(f'/api/disputes/{ident}/draft').json()
    assert drafted['citations'][0]['document_id'] == did
    assert 'project files were delivered' in drafted['draft_text']
    assert client.get(f'/api/disputes/{ident}/export').status_code == 409
    assert client.post(f'/api/disputes/{ident}/approve').json()['status'] == 'approved'
    exported = client.get(f'/api/disputes/{ident}/export')
    assert exported.status_code == 200 and 'SIMULATED' in exported.text
    assert client.put(f'/api/disputes/{ident}/response', json={'draft_text': 'Edited for review'}).json()['status'] == 'draft'
    assert client.get(f'/api/disputes/{ident}/export').status_code == 409
    summary = client.get('/api/dashboard/summary').json()
    assert summary['verified'] == 1 and summary['simulated_disputes'] == 1
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == 'dispute.approved')) == 1


def test_other_merchant_cannot_access_evidence_or_disputes(api):
    client, state, engine = api
    tid = create(client).json()['transaction']['id']
    did = upload(client, tid).json()['id']
    client.post('/api/disputes/sync')
    ident = client.get('/api/disputes').json()['items'][0]['id']
    token = client.post('/api/auth/login', json={'email': 'two@example.invalid', 'password': state['password']}).json()['access_token']
    client.headers['Authorization'] = 'Bearer ' + token
    for path in [f'/api/evidence/{did}/download', f'/api/transactions/{tid}/evidence', f'/api/transactions/{tid}/readiness', f'/api/disputes/{ident}/export']:
        assert client.get(path).status_code == 404
    assert client.post(f'/api/disputes/{ident}/approve').status_code == 404
    assert client.get('/api/disputes').json()['items'] == []
    assert client.get('/api/dashboard/summary').json()['transactions'] == 0


def test_invalid_scanned_and_oversized_pdfs(api):
    client, _, _ = api
    tid = create(client).json()['transaction']['id']
    assert upload(client, tid, b'not a PDF').status_code == 422
    assert upload(client, tid, b'%PDF-' + b'x' * 10_000_000).status_code == 413
    writer = PdfWriter(); writer.add_blank_page(width=100, height=100)
    out = io.BytesIO(); writer.write(out)
    assert upload(client, tid, out.getvalue()).status_code == 422


def test_fabricated_excerpt_rejected_and_provider_failure_keeps_analysis(api, monkeypatch):
    client, _, engine = api
    tid = create(client).json()['transaction']['id']
    upload(client, tid)
    false = candidate().model_copy(update={'excerpt': 'The buyer accepted everything.'})
    monkeypatch.setattr('app.services.gemini.extract', lambda pages: [candidate(), false])
    assert client.post(f'/api/transactions/{tid}/analyze').json()['accepted_facts'] == 1
    def unavailable(pages):
        raise HTTPException(502, 'Unavailable')
    monkeypatch.setattr('app.services.gemini.extract', unavailable)
    assert client.post(f'/api/transactions/{tid}/analyze').status_code == 502
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(ExtractedFact)) == 1


def test_contradiction_requires_review_and_empty_draft_is_honest(api, monkeypatch):
    client, _, _ = api
    tid = create(client).json()['transaction']['id']
    client.post('/api/disputes/sync')
    did = client.get('/api/disputes').json()['items'][0]['id']
    assert 'Insufficient evidence' in client.post(f'/api/disputes/{did}/draft').json()['draft_text']
    upload(client, tid)
    concern = candidate().model_copy(update={'supports_claim': False})
    monkeypatch.setattr('app.services.gemini.extract', lambda pages: [candidate(), concern])
    score = client.post(f'/api/transactions/{tid}/analyze').json()
    assert score['score'] == 0
    assert score['breakdown'][0]['status'] == 'review'
