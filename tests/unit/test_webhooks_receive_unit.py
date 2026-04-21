import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.infrastructure.db.models import Merchant, MerchantPlan
from app.main import app


def _yukassa_body(merchant_id: str | None) -> bytes:
    meta: dict[str, str] = {}
    if merchant_id is not None:
        meta["merchant_id"] = merchant_id
    payload = {
        "event_id": "evt_1",
        "event_type": "payment.succeeded",
        "object": {
            "id": "prov_1",
            "status": "succeeded",
            "metadata": meta,
        },
    }
    return json.dumps(payload).encode()


@pytest_asyncio.fixture
async def wh_client() -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


@pytest.mark.asyncio
async def test_yukassa_webhook_missing_merchant_id_400(wh_client: AsyncClient) -> None:
    db = MagicMock()
    db.execute = AsyncMock()

    async def _override_get_db() -> object:
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    try:
        r = await wh_client.post(
            "/webhooks/yukassa",
            content=_yukassa_body(None),
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 400
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_yukassa_webhook_merchant_not_found_404(wh_client: AsyncClient) -> None:
    db = MagicMock()
    rs = MagicMock()
    rs.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=rs)

    async def _override_get_db() -> object:
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    try:
        r = await wh_client.post(
            "/webhooks/yukassa",
            content=_yukassa_body("550e8400-e29b-41d4-a716-446655440000"),
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_yukassa_webhook_idempotent_returns_ok(wh_client: AsyncClient) -> None:
    mid = str(uuid.uuid4())
    merchant = MagicMock(spec=Merchant)
    merchant.id = mid
    merchant.plan = MerchantPlan.FREE

    existing_log = MagicMock()
    existing_log.id = uuid.uuid4()

    call_idx = {"n": 0}

    async def _exec(*_a: object, **_kw: object) -> MagicMock:
        call_idx["n"] += 1
        r = MagicMock()
        if call_idx["n"] == 1:
            r.scalar_one_or_none.return_value = merchant
        elif call_idx["n"] == 3:
            r.scalar_one_or_none.return_value = existing_log
        else:
            r.scalar_one_or_none.return_value = None
        return r

    db = MagicMock()
    db.execute = AsyncMock(side_effect=_exec)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    async def _override_get_db() -> object:
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    try:
        r = await wh_client.post(
            "/webhooks/yukassa",
            content=_yukassa_body(mid),
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data.get("idempotent") is True
    finally:
        app.dependency_overrides.clear()
