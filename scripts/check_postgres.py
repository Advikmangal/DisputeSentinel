"""Migration/concurrency acceptance on an EMPTY disposable PostgreSQL database.

Set TEST_DATABASE_URL in the environment (never a committed credential file).
This script refuses a database with tables, then creates and drops its test data.
PayPal is mocked; only the disposable PostgreSQL connection uses the network.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
from threading import Barrier
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import Base, database_url
from app.models import EvidenceDocument, Merchant, Transaction
from app.schemas.payments import CreateOrder
from app.services import payments
from app.services.paypal import PayPalClient


def main():
    value = os.environ.get("TEST_DATABASE_URL")
    if not value:
        raise SystemExit("Set TEST_DATABASE_URL to an empty disposable PostgreSQL database.")
    os.environ["DATABASE_URL"] = value
    get_settings.cache_clear()
    engine = create_engine(database_url(), hide_parameters=True)
    with engine.connect() as connection:
        tables = inspect(connection).get_table_names()
        if tables and tables != ["alembic_version"]:
            raise SystemExit("Refusing nonempty database: use a fresh disposable database.")
        if tables and connection.scalar(text("SELECT count(*) FROM alembic_version")):
            raise SystemExit("Refusing database with an existing migration revision.")
    config = Config(str(Path(__file__).resolve().parents[1] / "backend/alembic.ini"))
    command.upgrade(config, "head")
    print("PASS: alembic upgrade head (fresh PostgreSQL)")
    inspector = inspect(engine)
    assert set(inspector.get_table_names()) == set(Base.metadata.tables) | {"alembic_version"}
    data_column = next(c for c in inspector.get_columns("evidence_documents") if c["name"] == "file_data")
    assert str(data_column["type"]) == "BYTEA"
    for table, column in [("transactions", "paypal_order_id"), ("transactions", "paypal_capture_id"),
                          ("disputes", "paypal_dispute_id"), ("webhook_events", "paypal_event_id")]:
        assert any(c["column_names"] == [column] for c in inspector.get_unique_constraints(table))
    command.check(config)
    print("PASS: 9 tables, BYTEA, required unique constraints and no schema drift")

    with Session(engine) as db:
        merchant = Merchant(email="acceptance@example.invalid", password_hash="disabled")
        db.add(merchant)
        db.commit()
        merchant_id = merchant.id

    paypal = Mock(spec=PayPalClient)
    paypal.create_order.return_value = {
        "id": "ORDER-ACCEPTANCE", "status": "CREATED",
        "purchase_units": [{"amount": {"currency_code": "USD", "value": "1.00"}}],
        "links": [{"rel": "approve", "href": "https://www.sandbox.paypal.com/checkoutnow?token=ORDER-ACCEPTANCE"}],
    }
    barrier = Barrier(2)

    def create(_):
        with Session(engine, expire_on_commit=False) as db:
            barrier.wait(timeout=10)
            result = payments.create_order(db, paypal, merchant_id, CreateOrder(amount="1.00", currency="USD"), "same-key")
            return result["transaction"].id

    with ThreadPoolExecutor(max_workers=2) as workers:
        ids = list(workers.map(create, range(2)))
    assert ids[0] == ids[1] and paypal.create_order.call_count == 1
    print("PASS: concurrent create uses one PayPal request and one transaction")

    paypal.get_order.return_value = {
        "id": "ORDER-ACCEPTANCE", "intent": "CAPTURE", "status": "COMPLETED",
        "purchase_units": [{"amount": {"currency_code": "USD", "value": "1.00"}, "payments": {"captures": [
            {"id": "CAPTURE-ACCEPTANCE", "status": "COMPLETED", "create_time": "2026-11-07T10:00:00Z",
             "amount": {"currency_code": "USD", "value": "1.00"}}
        ]}}],
    }
    barrier = Barrier(2)

    def capture(_):
        with Session(engine, expire_on_commit=False) as db:
            barrier.wait(timeout=10)
            result = payments.capture_order(db, paypal, merchant_id, "ORDER-ACCEPTANCE")
            return result.id, result.status, result.paypal_capture_id

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(capture, range(2)))
    assert results[0] == results[1] == (ids[0], "VERIFIED", "CAPTURE-ACCEPTANCE")
    assert paypal.capture_order.call_count == paypal.get_order.call_count == 1
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(Transaction)) == 1
        document = EvidenceDocument(transaction_id=ids[0], filename="synthetic.pdf", mime_type="application/pdf",
                                    size=4, file_data=b"test", text_content="Synthetic storage check")
        db.add(document)
        db.commit()
        db.refresh(document)
        assert document.file_data == b"test"
    print("PASS: concurrent capture is a no-op on replay; BYTEA round trip succeeds")
    engine.dispose()
    command.downgrade(config, "base")
    with engine.connect() as connection:
        assert inspect(connection).get_table_names() == ["alembic_version"]
        assert connection.scalar(text("SELECT count(*) FROM alembic_version")) == 0
    print("PASS: alembic downgrade base (all 9 tables removed)")
    command.upgrade(config, "head")
    command.check(config)
    command.downgrade(config, "base")
    print("PASS: repeat upgrade/check/downgrade")
    engine.dispose()


if __name__ == "__main__":
    main()
