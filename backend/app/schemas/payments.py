from datetime import datetime, timezone
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, computed_field


class CreateOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: str = Field(pattern=r"^(?:0|[1-9][0-9]{0,15})(?:\.[0-9]{1,2})?$", max_length=19)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    description: str = Field(default="", max_length=1000)


class CaptureOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order_id: str = Field(pattern=r"^[A-Za-z0-9-]{1,127}$")


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    merchant_id: int
    paypal_order_id: str
    paypal_capture_id: str | None
    amount: Decimal
    currency: str
    status: str
    payer_email: str | None
    description: str
    created_at: datetime
    captured_at: datetime | None

    @computed_field
    @property
    def is_demo(self) -> bool:
        return self.paypal_order_id.startswith("DEMO-")

    @field_validator("created_at", "captured_at")
    @classmethod
    def utc_timestamp(cls, value):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class CreatedOrderOut(BaseModel):
    transaction: TransactionOut
    approval_url: str


class TransactionsOut(BaseModel):
    items: list[TransactionOut]
