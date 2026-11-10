from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Path
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import Transaction
from app.schemas.payments import CaptureOrder, CreatedOrderOut, CreateOrder, TransactionOut, TransactionsOut
from app.services import payments
from app.services.paypal import PayPalClient
from app.services.auth import get_merchant_id

router = APIRouter(prefix="/api", tags=["payments"])


@router.get("/payments/config")
def payment_config(merchant_id: Annotated[int, Depends(get_merchant_id)]):
    settings = get_settings()
    client_id = settings.paypal_client_id
    if not client_id or client_id.startswith("replace-"):
        raise HTTPException(503, "PayPal Sandbox client ID is not configured on the server.")
    return {"client_id": client_id, "currency": "USD", "environment": "sandbox"}


def get_paypal():
    try:
        client = PayPalClient(get_settings())
    except ValueError:
        raise HTTPException(503, detail={"code": "paypal_not_configured", "message": "Configure PayPal Sandbox credentials."}) from None
    with client:
        yield client


DB = Annotated[Session, Depends(get_db)]
MerchantID = Annotated[int, Depends(get_merchant_id)]
PayPal = Annotated[PayPalClient, Depends(get_paypal)]


@router.post("/payments/create-order", response_model=CreatedOrderOut, status_code=201)
def create_order(body: CreateOrder, merchant_id: MerchantID, db: DB, paypal: PayPal,
                 idempotency_key: Annotated[str, Header(pattern=r"^[A-Za-z0-9_-]{1,38}$")]):
    return payments.create_order(db, paypal, merchant_id, body, idempotency_key)


@router.post("/payments/capture", response_model=TransactionOut)
def capture_order(body: CaptureOrder, merchant_id: MerchantID, db: DB, paypal: PayPal):
    return payments.capture_order(db, paypal, merchant_id, body.order_id)


@router.get("/transactions", response_model=TransactionsOut)
def list_transactions(merchant_id: MerchantID, db: DB):
    return {"items": db.scalars(select(Transaction).where(Transaction.merchant_id == merchant_id).order_by(Transaction.id)).all()}


@router.get("/transactions/{id}", response_model=TransactionOut)
def transaction_detail(merchant_id: MerchantID, db: DB, id: Annotated[int, Path(gt=0)]):
    transaction = db.scalar(select(Transaction).where(Transaction.id == id, Transaction.merchant_id == merchant_id))
    if transaction is None:
        raise HTTPException(404, detail={"code": "transaction_not_found", "message": "Transaction not found."})
    return transaction

