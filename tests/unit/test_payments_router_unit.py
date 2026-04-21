import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.auth import inject_tenant
from app.infrastructure.db.tenant_models import PaymentProvider, PaymentStatus
from app.main import app


def _mock_payment(i: int) -> MagicMock:
    p = MagicMock()
    p.id = uuid.UUID(int=i)
    p.amount = Decimal("10")
    p.currency = "RUB"
    p.status = PaymentStatus.PENDING
    p.idempotency_key = f"k{i}"
    p.provider = PaymentProvider.YUKASSA
    p.provider_payment_id = None
    p.meta = {}
    p.created_at = datetime(2024, 1, 1, tzinfo=UTC)
    return p


@pytest_asyncio.fixture
async def pay_client() -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


@pytest.mark.asyncio
async def test_list_payments_returns_next_cursor(pay_client: AsyncClient) -> None:
    rows = [_mock_payment(i) for i in range(21)]
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    tenant_db = MagicMock()
    tenant_db.execute = AsyncMock(return_value=result)

    async def _override_inject() -> object:
        yield tenant_db

    app.dependency_overrides[inject_tenant] = _override_inject
    try:
        r = await pay_client.get("/payments?limit=20")
        assert r.status_code == 200
        body = r.json()
        assert body["next_cursor"] is not None
        assert len(body["items"]) == 20
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_payments_status_filter(pay_client: AsyncClient) -> None:
    p = _mock_payment(0)
    p.status = PaymentStatus.COMPLETED
    result = MagicMock()
    result.scalars.return_value.all.return_value = [p]
    tenant_db = MagicMock()
    tenant_db.execute = AsyncMock(return_value=result)

    async def _override_inject() -> object:
        yield tenant_db

    app.dependency_overrides[inject_tenant] = _override_inject
    try:
        r = await pay_client.get("/payments?status=completed")
        assert r.status_code == 200
        assert r.json()["next_cursor"] is None
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_payment_not_found_404(pay_client: AsyncClient) -> None:
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    tenant_db = MagicMock()
    tenant_db.execute = AsyncMock(return_value=result)

    async def _override_inject() -> object:
        yield tenant_db

    app.dependency_overrides[inject_tenant] = _override_inject
    try:
        r = await pay_client.get(f"/payments/{uuid.uuid4()}")
        assert r.status_code == 404
    finally:
        app.dependency_overrides.clear()
