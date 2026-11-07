"""Create a demo merchant using environment settings; never print credentials."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import select
from sqlalchemy.orm import Session
from app.config import get_settings
from app.db import get_engine
from app.models import Merchant
from app.services.auth import hash_password


def seed(db: Session, email: str, password: str) -> bool:
    email = email.strip().lower()
    if "@" not in email or len(email) > 320 or not 12 <= len(password) <= 1024 or password.startswith("replace-"):
        raise ValueError("Set DEMO_MERCHANT_EMAIL and a DEMO_MERCHANT_PASSWORD of 12–1024 characters.")
    merchant = db.scalar(select(Merchant).where(Merchant.email == email))
    if merchant:
        # Permit upgrading the disabled T2.2 local merchant, never reset a real hash.
        if merchant.password_hash.startswith("!login-disabled"):
            merchant.password_hash = hash_password(password)
            db.commit()
            return True
        return False
    db.add(Merchant(email=email, password_hash=hash_password(password)))
    db.commit()
    return True


def main():
    settings = get_settings()
    try:
        with Session(get_engine()) as db:
            changed = seed(db, settings.demo_merchant_email, settings.demo_merchant_password.get_secret_value())
        print("Demo merchant seeded." if changed else "Merchant already exists; password unchanged.")
    except Exception:
        print("Seed failed. Check database/migrations and DEMO_MERCHANT_EMAIL/PASSWORD settings; no credentials logged.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
