from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.main import app


@pytest_asyncio.fixture
async def st_client() -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


@pytest.mark.asyncio
async def test_mock_yukassa_status_payment_not_found(st_client: AsyncClient) -> None:
    db = MagicMock()
    call_n = {"n": 0}

    async def _exec(*_a: object, **_kw: object) -> MagicMock:
        call_n["n"] += 1
        r = MagicMock()
        if call_n["n"] >= 2:
            r.scalar_one_or_none.return_value = None
        return r

    db.execute = AsyncMock(side_effect=_exec)

    async def _override_get_db() -> object:
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    try:
        r = await st_client.get(
            "/mock/yukassa/status/prov-x",
            params={"merchant_id": "550e8400-e29b-41d4-a716-446655440000"},
        )
        assert r.status_code == 404
    finally:
        app.dependency_overrides.clear()
