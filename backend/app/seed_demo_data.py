"""Restore synthetic demo rows without modifying real payment history."""
from decimal import Decimal
from pathlib import Path
import sys
from uuid import NAMESPACE_URL, uuid5

from alembic import command
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_engine
from app.models import Merchant, Transaction
from app.seed_merchant import seed


def rebuild(db: Session, email: str, password: str) -> int:
    seed(db, email, password)
    merchant = db.scalar(select(Merchant).where(Merchant.email == email.strip().lower()).with_for_update())
    added = 0
    for index, amount in enumerate(("25.00", "75.00", "150.00")):
        order_id = "DEMO-" + str(uuid5(NAMESPACE_URL, f"demo:{merchant.email}:{index}"))
        if db.scalar(select(Transaction.id).where(Transaction.paypal_order_id == order_id)):
            continue
        db.add(Transaction(merchant_id=merchant.id, paypal_order_id=order_id,
                           amount=Decimal(amount), currency="USD", status="CREATED",
                           payer_email=f"demo-buyer-{index + 1}@example.invalid",
                           description=f"[DEMO - SIMULATED] Sample service {index + 1}; no PayPal payment"))
        added += 1
    db.commit()
    return added


def main():
    try:
        settings = get_settings()
        command.upgrade(Config(str(Path(__file__).resolve().parents[1] / "alembic.ini")), "head")
        with Session(get_engine()) as db:
            count = rebuild(db, settings.demo_merchant_email, settings.demo_merchant_password.get_secret_value())
        print(f"Demo data ready: {count} synthetic transactions added; existing records unchanged.")
    except Exception:
        print("Demo rebuild failed. Check database access and demo merchant environment settings.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
