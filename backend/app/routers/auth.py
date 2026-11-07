import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Merchant
from app.services.auth import TOKEN_SECONDS, hash_password, issue_token, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])
# Equalize password hashing work for nonexistent merchants. Not a login credential.
DUMMY_HASH = hash_password(secrets.token_urlsafe(32))


class Login(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)


@router.post("/login")
def login(body: Login, db: Session = Depends(get_db)):
    merchant = db.scalar(select(Merchant).where(Merchant.email == body.email.strip().lower()))
    valid = verify_password(body.password, merchant.password_hash if merchant else DUMMY_HASH)
    if not merchant or not valid:
        raise HTTPException(401, "Invalid email or password.", headers={"WWW-Authenticate": "Bearer"})
    return {"access_token": issue_token(merchant.id), "token_type": "bearer", "expires_in": TOKEN_SECONDS}
