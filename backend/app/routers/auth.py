import secrets
import re
import time
from collections import deque
from threading import Lock
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Merchant, Transaction
from app.services.auth import TOKEN_SECONDS, hash_password, issue_token, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])
# Equalize password hashing work for nonexistent merchants. Not a login credential.
DUMMY_HASH = hash_password(secrets.token_urlsafe(32))
signup_attempts = deque()
signup_lock = Lock()


def limit_signup(request: Request):
    # Bounded, process-local protection for the single-instance portfolio demo.
    now = time.monotonic()
    host = request.client.host if request.client else 'unknown'
    with signup_lock:
        while signup_attempts and signup_attempts[0][0] <= now - 60:
            signup_attempts.popleft()
        if len(signup_attempts) >= 30 or sum(ip == host for _, ip in signup_attempts) >= 5:
            raise HTTPException(429, 'Too many signup attempts. Try again in a minute.', headers={'Retry-After': '60'})
        signup_attempts.append((now, host))


class Login(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)


class Register(Login):
    password: str = Field(min_length=12, max_length=128)

    @field_validator('email')
    @classmethod
    def valid_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+", value):
            raise ValueError('Enter a valid email address.')
        local = value.split('@')[0]
        if len(local) > 64 or local.startswith('.') or local.endswith('.') or '..' in local:
            raise ValueError('Enter a valid email address.')
        return value


@router.post('/register', status_code=201, dependencies=[Depends(limit_signup)])
def register(body: Register, db: Session = Depends(get_db)):
    if db.scalar(select(Merchant.id).where(Merchant.email == body.email)):
        raise HTTPException(409, 'An account with this email already exists. Sign in instead.')
    merchant = Merchant(email=body.email, password_hash=hash_password(body.password))
    db.add(merchant)
    try:
        db.flush()
        token = issue_token(merchant.id)
        for index, amount in enumerate((25, 75, 150), 1):
            db.add(Transaction(merchant_id=merchant.id, paypal_order_id='DEMO-' + str(uuid4()),
                               amount=amount, currency='USD', status='CREATED',
                               description=f'[DEMO - SIMULATED] Sample service {index}; no PayPal payment'))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'An account with this email already exists. Sign in instead.') from None
    return {'access_token': token, 'token_type': 'bearer', 'expires_in': TOKEN_SECONDS}


@router.post("/login")
def login(body: Login, db: Session = Depends(get_db)):
    merchant = db.scalar(select(Merchant).where(Merchant.email == body.email.strip().lower()))
    valid = verify_password(body.password, merchant.password_hash if merchant else DUMMY_HASH)
    if not merchant or not valid:
        raise HTTPException(401, "Invalid email or password.", headers={"WWW-Authenticate": "Bearer"})
    return {"access_token": issue_token(merchant.id), "token_type": "bearer", "expires_in": TOKEN_SECONDS}
