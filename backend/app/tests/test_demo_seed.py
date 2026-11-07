import secrets

import pytest
from pydantic import SecretStr
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.main import create_app
from app.models import Merchant, Transaction
from app.seed_demo_data import rebuild
from app.services.auth import verify_password
from app.tests.test_payments import api


def test_production_startup_seeds_once_and_never_resets_password(api, monkeypatch):
    _, state, engine = api
    monkeypatch.setattr("app.seed_merchant.get_engine", lambda: engine)
    settings = Settings(_env_file=None, environment="production", jwt_secret=secrets.token_hex(32),
                        frontend_origin="https://frontend.example.invalid",
                        demo_merchant_email="startup@example.invalid", demo_merchant_password=state["password"])
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").status_code == 200
    with Session(engine) as db:
        merchant = db.scalar(select(Merchant).where(Merchant.email == settings.demo_merchant_email))
        encoded = merchant.password_hash
        assert verify_password(state["password"], encoded)
    settings.demo_merchant_password = SecretStr("different-synthetic-password")
    with TestClient(create_app(settings)):
        pass
    with Session(engine) as db:
        assert db.scalar(select(Merchant).where(Merchant.email == settings.demo_merchant_email)).password_hash == encoded


def test_missing_seed_password_prevents_production_startup(api, monkeypatch):
    _, _, engine = api
    monkeypatch.setattr("app.seed_merchant.get_engine", lambda: engine)
    settings = Settings(_env_file=None, environment="production", jwt_secret=secrets.token_hex(32),
                        frontend_origin="https://frontend.example.invalid",
                        demo_merchant_email="missing@example.invalid", demo_merchant_password="")
    with pytest.raises(RuntimeError, match="initialization failed"):
        with TestClient(create_app(settings)):
            pass


def test_demo_rebuild_is_repeatable_marked_and_not_capturable(api):
    client, state, engine = api
    with Session(engine) as db:
        original_hash = db.get(Merchant, 1).password_hash
        assert rebuild(db, "one@example.invalid", state["password"]) == 3
        assert rebuild(db, "one@example.invalid", "different-synthetic-password") == 0
        assert db.get(Merchant, 1).password_hash == original_hash
    items = client.get("/api/transactions").json()["items"]
    assert len(items) == 3
    for item in items:
        assert item["is_demo"] and item["status"] == "CREATED"
        assert item["paypal_capture_id"] is None
        response = client.post("/api/payments/capture", json={"order_id": item["paypal_order_id"]})
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "demo_transaction"
    assert state["calls"] == []


def test_rebuild_creates_missing_merchant_and_preserves_real_rows(api):
    _, state, engine = api
    with Session(engine) as db:
        db.add(Transaction(merchant_id=1, paypal_order_id="REAL-SYNTHETIC-TEST", amount=1,
                           currency="USD", status="CREATED", description="Untouched"))
        db.commit()
        assert rebuild(db, "new-demo@example.invalid", state["password"]) == 3
        real = db.scalar(select(Transaction).where(Transaction.paypal_order_id == "REAL-SYNTHETIC-TEST"))
        assert real.description == "Untouched"
