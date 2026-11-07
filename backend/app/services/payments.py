"""Persist Sandbox orders and verify capture data fetched directly from PayPal."""

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import AuditLog, Merchant, Transaction
from app.schemas.payments import CreateOrder
from app.services.paypal import PayPalClient, PayPalError


class PaymentError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message
        super().__init__(message)


def fail(status, code, message):
    raise PaymentError(status, code, message)


def upstream(error: PayPalError):
    if error.status_code == 422:
        fail(409, "paypal_state_conflict", "PayPal rejected the order state; it may not be approved.")
    if error.status_code == 404:
        fail(404, "paypal_order_not_found", "Order was not found in PayPal Sandbox.")
    fail(502, "paypal_failure", "PayPal Sandbox request failed. Retry with the same request ID.")


def merchant_lock(db: Session, merchant_id: int):
    if db.scalar(select(Merchant).where(Merchant.id == merchant_id).with_for_update()) is None:
        fail(503, "merchant_not_configured", "Configure an existing local demo merchant before using payment routes.")


def create_order(db: Session, paypal: PayPalClient, merchant_id: int,
                 body: CreateOrder, key: str):
    amount = Decimal(body.amount)
    if amount <= 0:
        fail(422, "invalid_amount", "Amount must be greater than zero.")
    normalized = {**body.model_dump(), "amount": format(amount, ".2f")}
    fingerprint = hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest()
    request_id = str(uuid5(NAMESPACE_URL, f"payoutsentinel:create:{merchant_id}:{key}"))

    def lookup():
        merchant_lock(db, merchant_id)
        return db.scalar(select(AuditLog).execution_options(populate_existing=True).where(
            AuditLog.merchant_id == merchant_id,
            AuditLog.action == "payment.create_requested",
            AuditLog.detail["request_id"].as_string() == request_id,
        ))

    entry = lookup()
    if entry is None:
        # Reserve the key and payload durably BEFORE the external side effect.
        # Reuse the planned audit table; no extra idempotency table is introduced.
        entry = AuditLog(merchant_id=merchant_id, action="payment.create_requested",
                         entity_type="merchant", entity_id=merchant_id,
                         detail={"request_id": request_id, "fingerprint": fingerprint})
        db.add(entry)
        db.commit()
        entry = lookup()  # serialize concurrent retries across processes
    if entry.detail["fingerprint"] != fingerprint:
        fail(409, "idempotency_conflict", "This idempotency key was used with a different payload.")
    if entry.entity_type == "transaction":
        transaction = db.get(Transaction, entry.entity_id)
        if transaction is None or transaction.merchant_id != merchant_id:
            fail(409, "reconciliation_required", "The stored order needs reconciliation.")
        return {"transaction": transaction, "approval_url": entry.detail["approval_url"]}
    created = entry.created_at.replace(tzinfo=timezone.utc) if entry.created_at.tzinfo is None else entry.created_at
    if datetime.now(timezone.utc) - created > timedelta(hours=5):
        fail(409, "reconciliation_required", "An old unfinished create request needs reconciliation before retrying.")
    try:
        order = paypal.create_order(normalized["amount"], body.currency, request_id=request_id)
    except PayPalError as error:
        upstream(error)
    try:
        order_id = order["id"]
        if not isinstance(order_id, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,127}", order_id):
            raise ValueError
        approval = next(link["href"] for link in order["links"] if link["rel"] in ("approve", "payer-action"))
        parsed = urlparse(approval)
        if parsed.scheme != "https" or parsed.hostname != "www.sandbox.paypal.com" or parsed.username:
            raise ValueError
        units = order["purchase_units"]
        if len(units) != 1 or not matches(units[0]["amount"], amount, body.currency):
            raise ValueError
        if order.get("status") not in ("CREATED", "PAYER_ACTION_REQUIRED", "APPROVED"):
            raise ValueError
    except (KeyError, TypeError, ValueError, StopIteration):
        fail(502, "invalid_paypal_response", "PayPal returned an invalid order response.")
    transaction = Transaction(merchant_id=merchant_id, paypal_order_id=order_id,
                              amount=amount, currency=body.currency, status="CREATED",
                              description=body.description)
    db.add(transaction)
    try:
        db.flush()
        entry.entity_type, entry.entity_id = "transaction", transaction.id
        entry.detail = {**entry.detail, "approval_url": approval}
        db.commit()
    except IntegrityError:
        db.rollback()
        fail(409, "order_conflict", "This PayPal order is already associated with a transaction.")
    return {"transaction": transaction, "approval_url": approval}


def matches(value, amount: Decimal, currency: str) -> bool:
    try:
        numeric = Decimal(value["value"])
        return numeric.is_finite() and numeric == amount and value["currency_code"] == currency
    except (KeyError, TypeError, ValueError, InvalidOperation):
        return False


def capture_order(db: Session, paypal: PayPalClient, merchant_id: int, order_id: str):
    transaction = db.scalar(select(Transaction).where(
        Transaction.merchant_id == merchant_id, Transaction.paypal_order_id == order_id,
    ).with_for_update())
    if transaction is None:
        fail(404, "order_not_found", "No order with this ID belongs to the current merchant.")
    if transaction.status == "VERIFIED":
        return transaction
    try:
        paypal.capture_order(order_id)
        order = paypal.get_order(order_id)  # never trust the capture response/browser
    except PayPalError as error:
        upstream(error)
    try:
        units = order["purchase_units"]
        if order["id"] != order_id or order["status"] != "COMPLETED" or order["intent"] != "CAPTURE":
            fail(409, "capture_not_completed", "PayPal has not completed this order's capture.")
        if len(units) != 1 or not matches(units[0]["amount"], transaction.amount, transaction.currency):
            fail(409, "amount_mismatch", "PayPal order amount or currency does not match the stored transaction.")
        captures = units[0]["payments"]["captures"]
        if len(captures) != 1 or captures[0]["status"] != "COMPLETED":
            fail(409, "capture_not_completed", "Expected exactly one completed PayPal capture.")
        capture = captures[0]
        if not matches(capture["amount"], transaction.amount, transaction.currency):
            fail(409, "amount_mismatch", "PayPal capture amount or currency does not match the stored transaction.")
        capture_id = capture["id"]
        if not isinstance(capture_id, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,127}", capture_id):
            raise ValueError
        captured_at = datetime.fromisoformat(capture["create_time"].replace("Z", "+00:00"))
        if captured_at.tzinfo is None:
            raise ValueError
        payer_email = order.get("payer", {}).get("email_address")
        if payer_email is not None and (not isinstance(payer_email, str) or len(payer_email) > 320):
            raise ValueError
    except (KeyError, TypeError, ValueError, IndexError, AttributeError):
        fail(502, "invalid_paypal_response", "PayPal returned incomplete or invalid capture data.")
    transaction.paypal_capture_id = capture_id
    transaction.status = "VERIFIED"
    transaction.captured_at = captured_at
    transaction.payer_email = payer_email
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        fail(409, "capture_conflict", "This PayPal capture is already associated with a transaction.")
    return transaction
