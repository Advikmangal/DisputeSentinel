import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import Merchant

TOKEN_SECONDS = 12 * 60 * 60
bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, salt, expected = encoded.split("$")
        if scheme != "scrypt" or len(salt) != 32 or len(expected) != 64:
            return False
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1, dklen=32)
        return hmac.compare_digest(actual, bytes.fromhex(expected))
    except (ValueError, TypeError):
        return False


def signing_key() -> str:
    secret = get_settings().jwt_secret.get_secret_value()
    if len(secret.encode()) < 32 or secret.startswith("replace-"):
        raise HTTPException(503, "Configure a random JWT_SECRET of at least 32 bytes.")
    return secret


def issue_token(merchant_id: int) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": str(merchant_id), "iat": now, "exp": now + timedelta(seconds=TOKEN_SECONDS),
                       "iss": "payoutsentinel", "aud": "payoutsentinel-api"}, signing_key(), algorithm="HS256")


def unauthorized():
    return HTTPException(401, "Invalid or expired authentication token.", headers={"WWW-Authenticate": "Bearer"})


def require_api_auth(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    path = request.url.path.rstrip("/")
    if not (path == "/api" or path.startswith("/api/")) or path in ("/api/auth/login", "/api/auth/register", "/api/webhooks/paypal"):
        return None
    if credentials is None:
        raise unauthorized()
    try:
        payload = jwt.decode(credentials.credentials, signing_key(), algorithms=["HS256"],
                             issuer="payoutsentinel", audience="payoutsentinel-api",
                             options={"require": ["sub", "iat", "exp", "iss", "aud"]})
        subject = payload["sub"]
        if not isinstance(subject, str) or not subject.isascii() or not subject.isdigit() or not 0 < int(subject) < 2**31:
            raise unauthorized()
        return int(subject)
    except (jwt.InvalidTokenError, TypeError, ValueError, OverflowError):
        raise unauthorized() from None


def get_merchant_id(merchant_id: int = Depends(require_api_auth), db: Session = Depends(get_db)) -> int:
    if merchant_id is None or db.get(Merchant, merchant_id) is None:
        raise unauthorized()
    return merchant_id
