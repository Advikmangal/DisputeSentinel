from datetime import datetime, timedelta, timezone
from decimal import Decimal

import secrets
import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import Settings, get_settings
from app.db import Base, get_db
from app.main import app
from app.models import AuditLog, Merchant, Transaction
from app.routers.payments import get_paypal
from app.services.auth import hash_password
from app.services.paypal import PayPalClient


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", secrets.token_hex(32))
    get_settings.cache_clear()
    password = secrets.token_urlsafe(20)
    password_hash = hash_password(password)
    """SQLite is only an isolated unit-test store; production uses PostgreSQL."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    event.listen(engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([Merchant(id=1, email="one@example.invalid", password_hash=password_hash),
                    Merchant(id=2, email="two@example.invalid", password_hash=password_hash)])
        db.commit()
    state = {"status": "APPROVED", "calls": [], "order_amount": "1.00", "capture_amount": "1.00",
             "currency": "USD", "create_status": 201, "capture_status": 201,
             "get_status": 200, "capture_id": "CAPTURE-1", "get_count": 0}

    def handler(request):
        state["calls"].append(request)
        path = request.url.path
        if path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "fake-token", "expires_in": 100, "token_type": "Bearer"})
        if request.method == "POST" and path.endswith("/orders"):
            return httpx.Response(state["create_status"], json={"id": "ORDER-1", "status": "CREATED",
                "purchase_units": [{"amount": {"currency_code": "USD", "value": "1.00"}}],
                "links": [{"rel": "approve", "href": "https://www.sandbox.paypal.com/checkoutnow?token=ORDER-1"}]})
        if request.method == "POST" and path.endswith("/capture"):
            if state["capture_status"] == 201:
                state["status"] = "COMPLETED"
            # Intentionally not trusted: capture's response has no payment data.
            return httpx.Response(state["capture_status"], json={"status": "COMPLETED"})
        state["get_count"] += 1
        order = {"id": state.get("fetched_id", "ORDER-1"), "intent": "CAPTURE", "status": state["status"],
            "payer": {"email_address": "buyer@example.invalid"},
            "purchase_units": [{"amount": {"currency_code": state["currency"], "value": state["order_amount"]},
                "payments": {"captures": [{"id": state["capture_id"], "status": state.get("capture_payment_status", "COMPLETED"),
                    "amount": {"currency_code": state["currency"], "value": state["capture_amount"]},
                    "create_time": "2026-11-07T10:00:00Z"}]}}]}
        if state.get("malformed") and state["status"] == "COMPLETED":
            order = {"id": "ORDER-1", "status": "COMPLETED"}
        if state.get("post_capture_pending") and state["get_count"] >= 2:
            order["status"] = "APPROVED"
        return httpx.Response(state["get_status"], json=order)

    paypal = PayPalClient(Settings(_env_file=None, paypal_client_id="test-client", paypal_client_secret="test-secret"),
                          transport=httpx.MockTransport(handler))

    def database():
        with Session(engine, expire_on_commit=False) as db:
            yield db

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_paypal] = lambda: paypal
    with TestClient(app) as client:
        state["password"] = password
        login = client.post("/api/auth/login", json={"email": "one@example.invalid", "password": password})
        assert login.status_code == 200
        client.headers["Authorization"] = "Bearer " + login.json()["access_token"]
        yield client, state, engine
    app.dependency_overrides.clear()
    get_settings.cache_clear()
    paypal.close()
    engine.dispose()


def create(client, key="create-1", **changes):
    return client.post("/api/payments/create-order", headers={"Idempotency-Key": key},
                       json={"amount": "1.00", "currency": "USD", "description": "Demo", **changes})


def capture(client, order_id="ORDER-1"):
    return client.post("/api/payments/capture", json={"order_id": order_id})


def test_create_capture_list_and_detail(api):
    client, state, engine = api
    created = create(client)
    assert created.status_code == 201, created.text
    assert created.json()["transaction"]["status"] == "CREATED"
    captured = capture(client)
    assert captured.status_code == 200, captured.text
    tx = captured.json()
    assert tx["status"] == "VERIFIED" and tx["paypal_capture_id"] == "CAPTURE-1"
    assert tx["amount"] == "1.00" and tx["captured_at"] is not None
    assert client.get("/api/transactions").json()["items"] == [tx]
    assert client.get(f"/api/transactions/{tx['id']}").json() == tx
    assert state["calls"][-1].method == "GET"  # independent server-side verification
    assert state["get_count"] == 2
    money_posts = [r for r in state["calls"] if r.method == "POST" and "/orders" in r.url.path]
    assert len(money_posts) == 2
    assert all(r.headers["PayPal-Request-Id"] for r in money_posts)


def test_duplicate_capture_returns_same_record_without_paypal_call(api):
    client, state, engine = api
    create(client)
    first = capture(client)
    count = len(state["calls"])
    second = capture(client)
    assert second.status_code == 200 and second.json() == first.json()
    assert len(state["calls"]) == count
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(Transaction)) == 1


def test_duplicate_create_and_changed_payload(api):
    client, state, engine = api
    first = create(client)
    count = len(state["calls"])
    assert create(client).json() == first.json()
    assert len(state["calls"]) == count
    conflict = create(client, amount="2.00")
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "idempotency_conflict"
    assert len(state["calls"]) == count


@pytest.mark.parametrize("order_id,status", [("UNKNOWN", 404), ("../invalid", 422), ("", 422)])
def test_invalid_order_id(api, order_id, status):
    client, state, _ = api
    response = capture(client, order_id)
    assert response.status_code == status
    assert not state["calls"]


def test_unapproved_order(api):
    client, state, engine = api
    create(client)
    state.update(status="CREATED", capture_status=422)
    response = capture(client)
    assert response.status_code == 409
    assert "approved" in response.json()["detail"]["message"]
    with Session(engine) as db:
        assert db.get(Transaction, 1).status == "CREATED"
        assert db.get(Transaction, 1).paypal_capture_id is None


@pytest.mark.parametrize("change", [
    {"order_amount": "2.00"}, {"capture_amount": "0.01"}, {"currency": "EUR"},
    {"capture_amount": "NaN"}, {"capture_payment_status": "PENDING"},
    {"post_capture_pending": True}, {"fetched_id": "OTHER-ORDER"},
])
def test_verification_rejects_untrusted_capture_data(api, change):
    client, state, engine = api
    create(client)
    state.update(change)
    response = capture(client)
    assert response.status_code == 409, response.text
    with Session(engine) as db:
        tx = db.get(Transaction, 1)
        assert tx.status == "CREATED" and tx.paypal_capture_id is None


@pytest.mark.parametrize("stage", ["create_status", "capture_status", "get_status"])
def test_paypal_5xx_is_clear_and_does_not_verify(api, stage):
    client, state, engine = api
    if stage != "create_status":
        create(client)
    state[stage] = 500
    response = create(client) if stage == "create_status" else capture(client)
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "paypal_failure"
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(Transaction).where(Transaction.status == "VERIFIED")) == 0


def test_failed_create_reserves_key_and_retry_reuses_paypal_id(api):
    client, state, engine = api
    state["create_status"] = 500
    assert create(client).status_code == 502
    assert create(client, amount="2.00").status_code == 409
    state["create_status"] = 201
    assert create(client).status_code == 201
    requests = [r for r in state["calls"] if r.url.path.endswith("/orders")]
    assert len(requests) == 2
    assert requests[0].headers["PayPal-Request-Id"] == requests[1].headers["PayPal-Request-Id"]


def test_stale_pending_create_requires_reconciliation(api):
    client, state, engine = api
    state["create_status"] = 500
    assert create(client).status_code == 502
    with Session(engine) as db:
        entry = db.scalar(select(AuditLog))
        entry.created_at = datetime.now(timezone.utc) - timedelta(hours=6)
        db.commit()
    count = len(state["calls"])
    assert create(client).json()["detail"]["code"] == "reconciliation_required"
    assert len(state["calls"]) == count


def test_cross_merchant_access_and_duplicate_capture_id(api):
    client, state, engine = api
    create(client)
    with Session(engine) as db:
        db.add(Transaction(merchant_id=2, paypal_order_id="PRIVATE-ORDER", amount=Decimal("1.00"),
                           currency="USD", status="VERIFIED", paypal_capture_id="CAPTURE-1"))
        db.commit()
    assert client.get("/api/transactions/2").status_code == 404
    assert len(client.get("/api/transactions").json()["items"]) == 1
    assert capture(client, "PRIVATE-ORDER").status_code == 404
    response = capture(client)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "capture_conflict"


def test_malformed_paypal_response_is_safe(api):
    client, state, _ = api
    create(client)
    state["malformed"] = True
    assert capture(client).json()["detail"]["code"] == "invalid_paypal_response"


def test_client_cannot_assert_success_or_amount(api):
    client, state, _ = api
    response = client.post("/api/payments/capture", json={"order_id": "ORDER-1", "status": "COMPLETED", "amount": "1.00"})
    assert response.status_code == 422 and not state["calls"]
    assert create(client, amount="0").status_code == 422


def test_routes_reject_missing_token(api):
    client, state, _ = api
    del client.headers["Authorization"]
    response = client.get("/api/transactions")
    assert response.status_code == 401
    assert not state["calls"]
