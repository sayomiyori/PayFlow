import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import Boolean, DateTime, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class TenantBase(DeclarativeBase):
    """
    Separate Base for tenant-specific models

    Why we dont use common Base?
    Bcs tenant models living in different schemas
    And we dont want to Alembic try create they are in public schema
    """

    pass


class PaymentStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PaymentProvider(StrEnum):
    YUKASSA = "yukassa"
    STRIPE = "stripe"
    MANUAL = "manual"  # for test


class Payment(TenantBase):
    """
    Table for payments - living in tenant schema
    __table_args__ intentionally doesnt contain schema=
    Bcs we manage search_path dynamically
    """

    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3),
        default="RUB",
        nullable=False,
    )
    status: Mapped[PaymentStatus] = mapped_column(
        String(20),
        default=PaymentStatus.PENDING,
        nullable=False,
    )

    # Idempotency key for prevent double payments
    # If request repeated with the same key - return existing payment
    idempotency_key: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True
    )

    provider: Mapped[PaymentProvider] = mapped_column(
        String(20),
        default=PaymentProvider.YUKASSA,
        nullable=False,
    )

    # Payments ID in the external system (Yukassa, Stripe, etc.)
    provider_payment_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Arbitary metadata from merchant
    meta: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Outbox(TenantBase):
    """
    Outbox table - events buffer for Kafka

    Principe: sending in outbox in the same transaction as well business-object
    Worker reading itbox and public into kafka
    """

    __tablename__ = "outbox"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    event_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    aggregate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
    )
    processed: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Webhook(TenantBase):
    __tablename__ = "webhooks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class WebhookLog(TenantBase):
    __tablename__ = "webhook_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    event_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    signature_valid: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    processed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="received")
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
