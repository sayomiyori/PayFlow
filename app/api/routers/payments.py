import base64
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import get_current_merchant, inject_tenant
from app.infrastructure.db.models import Merchant
from app.infrastructure.db.tenant_models import Outbox, Payment, PaymentStatus

router = APIRouter(prefix="/payments", tags=["payments"])


class CreatePaymentRequest(BaseModel):
    amount: Decimal = Field(gt=0)
    currency: str = Field(default="RUB", min_length=3, max_length=3)
    provider: str = Field(default="yukassa", min_length=3, max_length=20)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PaymentResponse(BaseModel):
    id: uuid.UUID
    amount: Decimal
    currency: str
    status: str
    idempotency_key: str | None
    provider: str
    provider_payment_id: str | None
    metadata: dict[str, Any]
    created_at: datetime


class PaymentListResponse(BaseModel):
    items: list[PaymentResponse]
    next_cursor: str | None


def _payment_to_response(payment: Payment) -> PaymentResponse:
    return PaymentResponse(
        id=payment.id,
        amount=payment.amount,
        currency=payment.currency,
        status=str(payment.status),
        idempotency_key=payment.idempotency_key,
        provider=str(payment.provider),
        provider_payment_id=payment.provider_payment_id,
        metadata=payment.meta,
        created_at=payment.created_at,
    )


def _encode_cursor(created_at: datetime, payment_id: uuid.UUID) -> str:
    payload = {
        "created_at": created_at.astimezone(UTC).isoformat(),
        "id": str(payment_id),
    }
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        payload = json.loads(raw)
        return datetime.fromisoformat(payload["created_at"]), uuid.UUID(payload["id"])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Invalid cursor") from exc


@router.post("", response_model=PaymentResponse, status_code=status.HTTP_201_CREATED)
async def create_payment(
    payload: CreatePaymentRequest,
    response: Response,
    tenant_db: AsyncSession = Depends(inject_tenant),
    merchant: Merchant = Depends(get_current_merchant),
    idempotency_key: str | None = Header(
        default=None,
        alias="X-Idempotency-Key",
    ),
) -> PaymentResponse:
    if not idempotency_key:
        raise HTTPException(
            status_code=400,
            detail="X-Idempotency-Key header is required",
        )

    existing = await tenant_db.execute(
        select(Payment).where(Payment.idempotency_key == idempotency_key)
    )
    payment = existing.scalar_one_or_none()
    if payment:
        response.status_code = status.HTTP_200_OK
        return _payment_to_response(payment)

    payment = Payment(
        amount=payload.amount,
        currency=payload.currency.upper(),
        status=PaymentStatus.PENDING,
        idempotency_key=idempotency_key,
        provider=payload.provider,
        provider_payment_id=f"yk_{uuid.uuid4().hex}",
        meta={**payload.metadata, "merchant_id": str(merchant.id)},
    )
    tenant_db.add(payment)
    await tenant_db.flush()

    outbox_event = Outbox(
        event_type="payment.created",
        aggregate_id=payment.id,
        payload={
            "merchant_id": str(merchant.id),
            "payment_id": str(payment.id),
            "amount": str(payment.amount),
            "currency": payment.currency,
            "status": str(payment.status),
            "provider": str(payment.provider),
        },
        processed=False,
    )
    tenant_db.add(outbox_event)
    await tenant_db.commit()

    return _payment_to_response(payment)


@router.get("/{payment_id}", response_model=PaymentResponse)
async def get_payment(
    payment_id: uuid.UUID,
    tenant_db: AsyncSession = Depends(inject_tenant),
) -> PaymentResponse:
    result = await tenant_db.execute(select(Payment).where(Payment.id == payment_id))
    payment = result.scalar_one_or_none()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    return _payment_to_response(payment)


@router.get("", response_model=PaymentListResponse)
async def list_payments(
    tenant_db: AsyncSession = Depends(inject_tenant),
    status_filter: PaymentStatus | None = Query(default=None, alias="status"),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> PaymentListResponse:
    stmt: Select[tuple[Payment]] = select(Payment)

    if status_filter:
        stmt = stmt.where(Payment.status == status_filter)

    if cursor:
        cursor_created_at, cursor_id = _decode_cursor(cursor)
        stmt = stmt.where(
            (Payment.created_at < cursor_created_at)
            | ((Payment.created_at == cursor_created_at) & (Payment.id < cursor_id))
        )

    stmt = stmt.order_by(Payment.created_at.desc(), Payment.id.desc()).limit(limit + 1)
    result = await tenant_db.execute(stmt)
    rows = list(result.scalars().all())

    has_next = len(rows) > limit
    items = rows[:limit]
    next_cursor = None
    if has_next and items:
        last = items[-1]
        next_cursor = _encode_cursor(last.created_at, last.id)

    return PaymentListResponse(
        items=[_payment_to_response(item) for item in items],
        next_cursor=next_cursor,
    )
