import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.routers.payments import (
    _decode_cursor,
    _encode_cursor,
    _payment_to_response,
)


def test_payment_to_response_maps_fields() -> None:
    pid = uuid.uuid4()
    created = datetime(2024, 6, 1, 12, 0, tzinfo=UTC)
    payment = SimpleNamespace(
        id=pid,
        amount=Decimal("10.5"),
        currency="RUB",
        status="pending",
        idempotency_key="ik",
        provider="yukassa",
        provider_payment_id="prov-1",
        meta={"k": "v"},
        created_at=created,
    )
    resp = _payment_to_response(payment)  # type: ignore[arg-type]
    assert resp.id == pid
    assert resp.amount == Decimal("10.5")
    assert resp.metadata == {"k": "v"}


def test_encode_decode_cursor_roundtrip() -> None:
    pid = uuid.uuid4()
    ts = datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)
    cur = _encode_cursor(ts, pid)
    ts2, pid2 = _decode_cursor(cur)
    assert pid2 == pid
    assert ts2.replace(tzinfo=UTC) == ts


def test_decode_cursor_invalid_raises_http_400() -> None:
    with pytest.raises(HTTPException) as exc:
        _decode_cursor("not-base64!!!")
    assert exc.value.status_code == 400
