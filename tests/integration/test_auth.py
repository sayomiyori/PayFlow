from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from jose import jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import rate_limiter
from app.core.config import get_settings
from app.core.security import ALGORITHM

settings = get_settings()


@pytest.mark.asyncio
async def test_register_creates_merchant_and_schema(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """
    Registretion must:
    1. Return 201 from merchant_id and api_key
    2. Create note in DB
    3. Create PostgreSQL schema
    """
    response = await client.post(
        "/auth/register",
        json={
            "name": "Test Shop",
            "email": "test@shop.com",
            "password": "SecurePass123!",
            "plan": "free",
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert "merchant_id" in data
    assert "api_key" in data
    assert len(data["api_key"]) == 64

    # Checking what schema created in PostgreSQL
    schema_name = data["schema_name"]
    result = await db_session.execute(
        text(
            "SELECT schema_name FROM information_schema.schemata "
            "WHERE schema_name = :schema_name"
        ),
        {"schema_name": schema_name},
    )
    assert result.scalar_one_or_none() == schema_name


@pytest.mark.asyncio
async def test_register_duplicate_email_returns_409(client: AsyncClient):
    # Registering first time
    await client.post(
        "/auth/register",
        json={
            "name": "Shop 2",
            "email": "duplicate@test.com",
            "password": "Pass456!",
        },
    )

    response = await client.post(
        "/auth/register",
        json={
            "name": "Shop 2 Duplicate",
            "email": "duplicate@test.com",
            "password": "Pass456!",
        },
    )

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_login_returns_tokens(client: AsyncClient):
    # First registering
    await client.post(
        "/auth/register",
        json={
            "name": "Login Test",
            "email": "login@test.com",
            "password": "TestPass123!",
        },
    )

    # Login
    response = await client.post(
        "/auth/token",
        json={
            "email": "login@test.com",
            "password": "TestPass123!",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_token_payload_sub_matches_merchant_id(client: AsyncClient):
    register = await client.post(
        "/auth/register",
        json={
            "name": "Token Match",
            "email": "token_match@test.com",
            "password": "TestPass123!",
        },
    )
    assert register.status_code == 201
    merchant_id = register.json()["merchant_id"]

    login = await client.post(
        "/auth/token",
        json={
            "email": "token_match@test.com",
            "password": "TestPass123!",
        },
    )
    assert login.status_code == 200
    access_token = login.json()["access_token"]
    payload = jwt.decode(access_token, settings.secret_key, algorithms=[ALGORITHM])

    assert payload["sub"] == merchant_id


@pytest.mark.asyncio
async def test_login_wrong_password_returns_401(client: AsyncClient):
    await client.post(
        "/auth/register",
        json={
            "name": "Test",
            "email": "wrongpass@test.com",
            "password": "CorrectPass!",
        },
    )

    response = await client.post(
        "/auth/token",
        json={
            "email": "wrongpass@test.com",
            "password": "WrongPass!",
        },
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_tenant_isolation(client: AsyncClient, db_session: AsyncSession):
    """
    Two merchants must have diff schemas
    Checking that isolation works
    """
    resp1 = await client.post(
        "/auth/register",
        json={
            "name": "Merchant A",
            "email": "merchant_a@test.com",
            "password": "Pass123!",
        },
    )
    resp2 = await client.post(
        "/auth/register",
        json={
            "name": "Merchant B",
            "email": "merchant_b@test.com",
            "password": "Pass456!",
        },
    )

    schema_a = resp1.json()["schema_name"]
    schema_b = resp2.json()["schema_name"]

    # Schemas must be different
    assert schema_a != schema_b

    # Both schemas must exist in PostgreSQL
    for schema in [schema_a, schema_b]:
        result = await db_session.execute(
            text(
                "SELECT schema_name FROM information_schema.schemata "
                "WHERE schema_name = :name"
            ),
            {"name": schema},
        )
        assert result.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_expired_token_returns_401(client: AsyncClient):
    expired_token = jwt.encode(
        {
            "sub": "expired-user",
            "type": "access",
            "exp": datetime.now(UTC) - timedelta(minutes=1),
        },
        settings.secret_key,
        algorithm=ALGORITHM,
    )

    response = await client.get(
        "/protected/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_rate_limit_exceeded_returns_429(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    register = await client.post(
        "/auth/register",
        json={
            "name": "Rate Limit",
            "email": "rate_limit@test.com",
            "password": "TestPass123!",
        },
    )
    assert register.status_code == 201

    login = await client.post(
        "/auth/token",
        json={
            "email": "rate_limit@test.com",
            "password": "TestPass123!",
        },
    )
    assert login.status_code == 200
    access_token = login.json()["access_token"]

    monkeypatch.setattr(rate_limiter, "is_allowed", AsyncMock(return_value=(False, 0)))

    response = await client.get(
        "/protected/limited-ping",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert response.status_code == 429
