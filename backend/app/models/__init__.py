"""The nine tables from the project plan; no tables are created on import."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Integer, JSON, LargeBinary, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Merchant(Base):
    __tablename__ = "merchants"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("amount > 0", name="positive_amount"),
        CheckConstraint("status IN ('CREATED', 'VERIFIED')", name="status"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), index=True)
    paypal_order_id: Mapped[str] = mapped_column(String(127), unique=True)
    paypal_capture_id: Mapped[str | None] = mapped_column(String(127), unique=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(20), server_default="CREATED")
    payer_email: Mapped[str | None] = mapped_column(String(320))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EvidenceDocument(Base):
    __tablename__ = "evidence_documents"
    __table_args__ = (CheckConstraint("size >= 0 AND size <= 10000000", name="file_size"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"), index=True)
    filename: Mapped[str] = mapped_column(Text)
    storage_path: Mapped[str | None] = mapped_column(Text)
    file_data: Mapped[bytes] = mapped_column(LargeBinary)  # BYTEA on PostgreSQL
    mime_type: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer)
    text_content: Mapped[str | None] = mapped_column(Text)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExtractedFact(Base):
    __tablename__ = "extracted_facts"
    __table_args__ = (
        CheckConstraint("page > 0", name="page"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence"),
        CheckConstraint("length(excerpt) > 0", name="excerpt"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("evidence_documents.id"), index=True)
    fact_type: Mapped[str] = mapped_column(String(100))
    value: Mapped[str] = mapped_column(Text)
    page: Mapped[int] = mapped_column(Integer)
    excerpt: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)


class ReadinessScore(Base):
    __tablename__ = "readiness_scores"
    __table_args__ = (CheckConstraint("score >= 0 AND score <= 100", name="score"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"), index=True)
    score: Mapped[int] = mapped_column(Integer)
    breakdown: Mapped[dict[str, Any] | list[Any]] = mapped_column(JSON)
    missing_items: Mapped[list[Any]] = mapped_column(JSON)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Dispute(Base):
    __tablename__ = "disputes"
    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"), index=True)
    paypal_dispute_id: Mapped[str] = mapped_column(String(127), unique=True)
    reason: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(100))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    response_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_fixture: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    raw: Mapped[dict[str, Any]] = mapped_column(JSON)


class DisputeResponse(Base):
    __tablename__ = "dispute_responses"
    __table_args__ = (CheckConstraint("status IN ('draft', 'approved', 'submitted', 'exported')", name="status"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    dispute_id: Mapped[int] = mapped_column(ForeignKey("disputes.id"), index=True)
    draft_text: Mapped[str] = mapped_column(Text)
    citations: Mapped[list[Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="draft", server_default="draft")
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), index=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    entity_type: Mapped[str] = mapped_column(String(100))
    entity_id: Mapped[int] = mapped_column(Integer)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    paypal_event_id: Mapped[str] = mapped_column(String(127), unique=True)
    event_type: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
