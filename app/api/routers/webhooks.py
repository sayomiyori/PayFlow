import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime
from typing import Any, cast

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import get_current_merchant, inject_tenant
from app.core.config import get_settings
from app.core.database import get_db
from app.infrastructure.db.models import Merchant
from app.infrastructure.db.tenant import get_tenant_session
from app.infrastructure.db.tenant_models import (
    Outbox,
    Payment,
    PaymentStatus,
    WebhookLog,
)

router = APIRouter(tags=["webhooks"])
settings = get_settings()


class YukassaWebhookPaymentObject(BaseModel):
    id: str
    status: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class YukassaWebhookRequest(BaseModel):
    event_id: str
    event_type: str
    object: YukassaWebhookPaymentObject


class MockSendRequest(BaseModel):
    payment_id: str
    status: str | None = None
    new_status: str | None = None

    @model_validator(mode="after")
    def validate_status(self) -> "MockSendRequest":
        # [ЧТО] Поддерживает оба формата поля статуса: `status` и `new_status`.
        # [ПОЧЕМУ] Так endpoint совместим с manual-сценариями и уже существующими интеграционными тестами.
        # [ОСТОРОЖНО] Если переданы оба поля с разными значениями, будет ошибка валидации.
        if not self.status and not self.new_status:
            raise ValueError("Either status or new_status must be provided")
        if self.status and self.new_status and self.status != self.new_status:
            raise ValueError("status and new_status must be equal when both provided")
        return self

    @property
    def effective_status(self) -> str:
        return self.status or self.new_status or "pending"


def _verify_signature(payload_bytes: bytes, signature: str | None) -> bool:
    # [ЧТО] Проверяет подпись входящего webhook через HMAC-SHA256.
    # [ПОЧЕМУ] Это простой и надежный способ подтвердить, что источник знает shared-secret.
    # [ОСТОРОЖНО] Сравнивать подписи нужно только через compare_digest, иначе возможны timing attacks.
    if not signature:
        return False
    digest = hmac.new(
        settings.yukassa_webhook_secret.encode("utf-8"),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(digest, signature.strip())


def _resolve_payment_status(raw_status: str) -> PaymentStatus:
    # [ЧТО] Нормализует строковый статус webhook до enum статуса платежа в системе.
    # [ПОЧЕМУ] Единый enum не дает разъехаться статусам между API, БД и worker-ами.
    # [ОСТОРОЖНО] Новые статусы провайдера должны быть явно добавлены сюда, иначе будет 400.
    normalized = raw_status.strip().lower()
    mapping = {
        "pending": PaymentStatus.PENDING,
        "processing": PaymentStatus.PROCESSING,
        "succeeded": PaymentStatus.COMPLETED,
        "completed": PaymentStatus.COMPLETED,
        "canceled": PaymentStatus.CANCELLED,
        "cancelled": PaymentStatus.CANCELLED,
        "failed": PaymentStatus.FAILED,
    }
    if normalized not in mapping:
        raise HTTPException(
            status_code=400, detail=f"Unsupported payment status: {raw_status}"
        )
    return mapping[normalized]


async def _process_webhook_payload(
    tenant_db: AsyncSession,
    webhook_log: WebhookLog,
) -> None:
    # [ЧТО] Применяет webhook к платежу и пишет доменное событие в outbox в одной транзакции.
    # [ПОЧЕМУ] Outbox-паттерн гарантирует, что изменение статуса и событие публикации не разъедутся.
    # [ОСТОРОЖНО] Если provider_payment_id отсутствует в tenant-схеме, webhook помечается failed.
    payload = YukassaWebhookRequest.model_validate(webhook_log.payload)
    payment_obj = payload.object
    payment_status = _resolve_payment_status(payment_obj.status)

    payment_result = await tenant_db.execute(
        select(Payment).where(Payment.provider_payment_id == payment_obj.id)
    )
    payment = payment_result.scalar_one_or_none()
    if payment is None:
        raise ValueError(f"Payment not found by provider_payment_id={payment_obj.id}")

    payment.status = payment_status
    payment.updated_at = datetime.now(UTC)
    payment.meta = {
        **payment.meta,
        "last_webhook_event_id": payload.event_id,
        "last_webhook_event_type": payload.event_type,
    }

    tenant_db.add(
        Outbox(
            event_type="payment.status_changed",
            aggregate_id=payment.id,
            payload={
                "payment_id": str(payment.id),
                "provider_payment_id": payment.provider_payment_id,
                "status": payment.status.value,
                "event_id": payload.event_id,
            },
            processed=False,
        )
    )

    webhook_log.processed = True
    webhook_log.status = "processed"
    webhook_log.error_message = None
    webhook_log.processed_at = datetime.now(UTC)


@router.post("/webhooks/yukassa")
async def receive_yukassa_webhook(
    request: Request,
    signature: str | None = Header(default=None, alias="X-Webhook-Signature"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    body = await request.body()
    parsed_payload = YukassaWebhookRequest.model_validate_json(body)
    signature_valid = _verify_signature(body, signature)

    merchant_id = parsed_payload.object.metadata.get("merchant_id")
    if not merchant_id:
        raise HTTPException(
            status_code=400, detail="merchant_id missing in webhook metadata"
        )

    merchant_result = await db.execute(
        select(Merchant).where(Merchant.id == str(merchant_id))
    )
    merchant = merchant_result.scalar_one_or_none()
    if merchant is None:
        raise HTTPException(status_code=404, detail="Merchant not found")

    tenant_db = await get_tenant_session(db, str(merchant.id))
    existing = await tenant_db.execute(
        select(WebhookLog).where(WebhookLog.event_id == parsed_payload.event_id)
    )
    existing_log = existing.scalar_one_or_none()
    if existing_log:
        return {"ok": True, "idempotent": True, "webhook_id": str(existing_log.id)}

    webhook_log = WebhookLog(
        event_id=parsed_payload.event_id,
        source="yukassa",
        event_type=parsed_payload.event_type,
        payload=parsed_payload.model_dump(mode="json"),
        signature_valid=signature_valid,
        processed=False,
        status="received",
    )
    tenant_db.add(webhook_log)
    await tenant_db.flush()

    if not signature_valid:
        webhook_log.status = "failed"
        webhook_log.error_message = "Invalid webhook signature"
        await tenant_db.commit()
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    try:
        await _process_webhook_payload(tenant_db, webhook_log)
        await tenant_db.commit()
        return {"ok": True, "idempotent": False, "webhook_id": str(webhook_log.id)}
    except Exception as exc:  # noqa: BLE001
        webhook_log.status = "failed"
        webhook_log.error_message = str(exc)
        await tenant_db.commit()
        raise HTTPException(
            status_code=500, detail="Webhook processing failed"
        ) from exc


@router.get("/webhooks/{webhook_id}/replay")
async def replay_webhook(
    webhook_id: uuid.UUID,
    tenant_db: AsyncSession = Depends(inject_tenant),
    _merchant: Merchant = Depends(get_current_merchant),
) -> dict[str, Any]:
    webhook_result = await tenant_db.execute(
        select(WebhookLog).where(WebhookLog.id == webhook_id)
    )
    webhook_log = webhook_result.scalar_one_or_none()
    if webhook_log is None:
        raise HTTPException(status_code=404, detail="Webhook not found")
    if not webhook_log.signature_valid:
        raise HTTPException(
            status_code=400, detail="Cannot replay webhook with invalid signature"
        )

    try:
        await _process_webhook_payload(tenant_db, webhook_log)
        await tenant_db.commit()
    except Exception as exc:  # noqa: BLE001
        webhook_log.status = "failed"
        webhook_log.error_message = str(exc)
        await tenant_db.commit()
        raise HTTPException(status_code=500, detail="Replay failed") from exc

    return {"ok": True, "webhook_id": str(webhook_log.id), "status": webhook_log.status}


@router.post("/mock/yukassa/send")
async def mock_send_yukassa_webhook(
    payload: MockSendRequest,
    tenant_db: AsyncSession = Depends(inject_tenant),
    _merchant: Merchant = Depends(get_current_merchant),
) -> dict[str, Any]:
    payment_result = await tenant_db.execute(
        select(Payment).where(Payment.id == uuid.UUID(payload.payment_id))
    )
    payment = payment_result.scalar_one_or_none()
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")

    webhook_payload = {
        "event_id": f"evt_{uuid.uuid4().hex}",
        "event_type": "payment.waiting_for_capture",
        "object": {
            "id": payment.provider_payment_id or str(payment.id),
            "status": payload.effective_status,
            "metadata": {"merchant_id": payment.meta.get("merchant_id")},
        },
    }
    payload_bytes = json.dumps(webhook_payload, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(
        settings.yukassa_webhook_secret.encode("utf-8"),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()

    async with AsyncClient(
        transport=ASGITransport(app=cast(Any, requested_app())),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/webhooks/yukassa",
            content=payload_bytes,
            headers={
                "X-Webhook-Signature": signature,
                "Content-Type": "application/json",
            },
        )
    return {"status_code": response.status_code, "response": response.json()}


@router.get("/mock/yukassa/status/{provider_payment_id}")
async def mock_yukassa_status(
    provider_payment_id: str,
    merchant_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_db = await get_tenant_session(db, merchant_id)
    payment_result = await tenant_db.execute(
        select(Payment).where(Payment.provider_payment_id == provider_payment_id)
    )
    payment = payment_result.scalar_one_or_none()
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    mocked_status = payment.meta.get("mock_provider_status")
    return {
        "payment_id": provider_payment_id,
        "status": mocked_status or payment.status.value,
    }


def requested_app() -> FastAPI:
    from app.main import app as fastapi_app

    return fastapi_app
