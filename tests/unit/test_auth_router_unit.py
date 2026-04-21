import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.core.security import hash_password
from app.infrastructure.db.models import Merchant, MerchantPlan
from app.main import app


@pytest_asyncio.fixture
async def auth_api_client() -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


@pytest.mark.asyncio
async def test_register_duplicate_email_returns_409(auth_api_client: AsyncClient) -> None:
    db = MagicMock()
    taken = MagicMock()
    taken.scalar_one_or_none.return_value = MagicMock()
    db.execute = AsyncMock(return_value=taken)

    async def _override_get_db() -> object:
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    try:
        response = await auth_api_client.post(
            "/auth/register",
            json={
                "name": "A",
                "email": "dup@example.com",
                "password": "SecurePass123!",
                "plan": "free",
            },
        )
        assert response.status_code == 409
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_login_invalid_credentials_returns_401(auth_api_client: AsyncClient) -> None:
    db = MagicMock()
    merchant = MagicMock(spec=Merchant)
    merchant.hashed_password = hash_password("correct")
    rs = MagicMock()
    rs.scalar_one_or_none.return_value = merchant
    db.execute = AsyncMock(return_value=rs)

    async def _override_get_db() -> object:
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    try:
        response = await auth_api_client.post(
            "/auth/token",
            json={"email": "x@y.com", "password": "wrong-pass"},
        )
        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_login_deactivated_returns_403(auth_api_client: AsyncClient) -> None:
    db = MagicMock()
    merchant = MagicMock(spec=Merchant)
    merchant.id = str(uuid.uuid4())
    merchant.hashed_password = hash_password("SecurePass123!")
    merchant.is_active = False
    merchant.plan = MerchantPlan.FREE
    merchant.schema_name = "merchant_x"
    rs = MagicMock()
    rs.scalar_one_or_none.return_value = merchant
    db.execute = AsyncMock(return_value=rs)

    async def _override_get_db() -> object:
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    try:
        response = await auth_api_client.post(
            "/auth/token",
            json={"email": "x@y.com", "password": "SecurePass123!"},
        )
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()
