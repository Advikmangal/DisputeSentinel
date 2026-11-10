"""Verified, idempotent PayPal notifications; never capture money from a webhook."""
import json
from datetime import datetime, timezone
from fastapi import APIRouter, Request, HTTPException
from starlette.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.config import get_settings
from app.models import Transaction, WebhookEvent
from app.routers.payments import DB, PayPal
from app.services.paypal import PayPalError
from app.services.payments import capture_order, PaymentError

router = APIRouter()


def process(db, paypal, event, raw, headers):
    webhook_id = get_settings().paypal_webhook_id
    if not webhook_id or webhook_id.startswith('replace-'):
        raise HTTPException(503, 'Configure PAYPAL_WEBHOOK_ID before accepting notifications.')
    fields = {'auth_algo': 'paypal-auth-algo', 'cert_url': 'paypal-cert-url',
              'transmission_id': 'paypal-transmission-id', 'transmission_sig': 'paypal-transmission-sig',
              'transmission_time': 'paypal-transmission-time'}
    values = {key: headers.get(header, '') for key, header in fields.items()}
    if any(not value or len(value) > 4096 for value in values.values()):
        raise HTTPException(400, 'Missing or invalid PayPal signature headers.')
    # Embed the original event JSON unchanged, as required by PayPal postback verification.
    payload = json.dumps({**values, 'webhook_id': webhook_id})[:-1].encode() + b',"webhook_event":' + raw + b'}'
    try:
        result = paypal._request('POST', '/v1/notifications/verify-webhook-signature',
                                 content=payload, headers={'Content-Type': 'application/json'})
    except PayPalError:
        raise HTTPException(502, 'PayPal signature verification unavailable; retry delivery.') from None
    if result.get('verification_status') != 'SUCCESS':
        raise HTTPException(400, 'Invalid PayPal signature.')
    stored = db.scalar(select(WebhookEvent).where(WebhookEvent.paypal_event_id == event['id']).with_for_update())
    if stored and stored.processed_at:
        return {'status': 'ok', 'duplicate': True}
    if stored is None:
        stored = WebhookEvent(paypal_event_id=event['id'], event_type=event['event_type'], payload=event)
        try:
            with db.begin_nested():
                db.add(stored)
                db.flush()
        except IntegrityError:
            stored = db.scalar(select(WebhookEvent).where(WebhookEvent.paypal_event_id == event['id']).with_for_update())
            if stored and stored.processed_at:
                return {'status': 'ok', 'duplicate': True}
    if event['event_type'] == 'PAYMENT.CAPTURE.COMPLETED':
        try:
            resource = event['resource']
            order_id = resource['supplementary_data']['related_ids']['order_id']
            capture_id = resource['id']
            if not isinstance(order_id, str) or not isinstance(capture_id, str):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise HTTPException(400, 'Invalid capture event.') from None
        tx = db.scalar(select(Transaction).where(Transaction.paypal_order_id == order_id).with_for_update())
        if tx is None:
            # The create request may not have committed yet; leave delivery retryable.
            raise HTTPException(503, 'Order is not yet available for reconciliation.')
        try:
            tx = capture_order(db, paypal, tx.merchant_id, order_id, reconcile_only=True, commit=False)
        except PaymentError:
            raise HTTPException(502, 'Capture reconciliation failed; retry delivery.') from None
        if tx.paypal_capture_id != capture_id:
            db.rollback()
            raise HTTPException(400, 'Capture event does not match the verified order.')
    stored.processed_at = datetime.now(timezone.utc)
    db.commit()
    return {'status': 'ok', 'duplicate': False}


@router.post('/api/webhooks/paypal')
async def webhook(request: Request, db: DB, paypal: PayPal):
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 1_000_000:
            raise HTTPException(413, 'Webhook too large.')
    try:
        event = json.loads(raw)
        if not isinstance(event, dict) or any(not isinstance(event.get(k), str) or not 1 <= len(event[k]) <= limit
                for k, limit in [('id', 127), ('event_type', 100)]):
            raise ValueError
    except (ValueError, UnicodeError):
        raise HTTPException(400, 'Malformed webhook.') from None
    return await run_in_threadpool(process, db, paypal, event, bytes(raw), request.headers)
