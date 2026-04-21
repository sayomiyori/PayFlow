import hashlib
import hmac
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.routers.webhooks import (
    MockSendRequest,
    _process_webhook_payload,
    _resolve_payment_status,
    _verify_signature,
)
from app.core.config import get_settings
from app.infrastructure.db.tenant_models import PaymentStatus


def test_mock_send_request_effective_status_prefers_status() -> None:
    m = MockSendRequest(payment_id="p1", status="completed")
    assert m.effective_status == "completed"


def test_mock_send_request_requires_status_or_new_status() -> None:
    with pytest.raises(ValidationError):
        MockSendRequest(payment_id="p1")


def test_mock_send_request_both_statuses_must_match() -> None:
    with pytest.raises(ValidationError):
        MockSendRequest(payment_id="p1", status="a", new_status="b")


def test_verify_signature_missing_returns_false() -> None:
    assert _verify_signature(b"{}", None) is False


def test_verify_signature_valid_roundtrip() -> None:
    settings = get_settings()
    body = b'{"x":1}'
    digest = hmac.new(
        settings.yukassa_webhook_secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    assert _verify_signature(body, digest) is True


def test_verify_signature_wrong_returns_false() -> None:
    assert _verify_signature(b"{}", "deadbeef") is False


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("pending", PaymentStatus.PENDING),
        ("PROCESSING ", PaymentStatus.PROCESSING),
        ("succeeded", PaymentStatus.COMPLETED),
        ("completed", PaymentStatus.COMPLETED),
        ("cancelled", PaymentStatus.CANCELLED),
        ("canceled", PaymentStatus.CANCELLED),
        ("failed", PaymentStatus.FAILED),
    ],
)
def test_resolve_payment_status_maps(raw: str, expected: PaymentStatus) -> None:
    assert _resolve_payment_status(raw) == expected


def test_resolve_payment_status_unknown_raises() -> None:
    with pytest.raises(HTTPException) as exc:
        _resolve_payment_status("weird")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_process_webhook_payload_updates_payment_and_outbox() -> None:
    payment = MagicMock()
    payment.id = uuid.uuid4()
    payment.provider_payment_id = "prov-1"
    payment.meta = {"old": True}
    payment.status = PaymentStatus.PROCESSING

    pr = MagicMock()
    pr.scalar_one_or_none.return_value = payment
    tenant_db = MagicMock()
    tenant_db.execute = AsyncMock(return_value=pr)

    log = MagicMock()
    log.payload = {
        "event_id": "e1",
        "event_type": "payment.succeeded",
        "object": {"id": "prov-1", "status": "succeeded", "metadata": {}},
    }

    await _process_webhook_payload(tenant_db, log)  # type: ignore[arg-type]

    assert payment.status == PaymentStatus.COMPLETED
    tenant_db.add.assert_called_once()
    assert log.processed is True
    assert log.status == "processed"


@pytest.mark.asyncio
async def test_process_webhook_payload_missing_payment_raises() -> None:
    pr = MagicMock()
    pr.scalar_one_or_none.return_value = None
    tenant_db = MagicMock()
    tenant_db.execute = AsyncMock(return_value=pr)

    log = MagicMock()
    log.payload = {
        "event_id": "e1",
        "event_type": "payment.succeeded",
        "object": {"id": "missing", "status": "succeeded", "metadata": {}},
    }

    with pytest.raises(ValueError, match="Payment not found"):
        await _process_webhook_payload(tenant_db, log)  # type: ignore[arg-type]
