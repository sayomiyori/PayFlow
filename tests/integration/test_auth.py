import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text 


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
    response = await client.post("/auth/register", json={
        "name": "Test Shop",
        "email": "test@shop.com",
        "password": "SecurePass123!",
        "plan": "free",
    })

    assert response.status_code == 201
    data = response.json()
    assert "merchant_id" in data
    assert "api_key" in data
    assert len(data["api_key"]) == 64


    #Checking what schema created in PostgreSQL
    schema_name = data["schema_name"]
    result = await db_session.execute(
        text("SELECT schema_name FROM information_schema.schemata WHERE schema_name = :schema_name"),
        {"schema_name": schema_name},
    )
    assert result.scalar_one_or_none() == schema_name


@pytest.mark.asyncio
async def test_register_duplicate_email_returns_409(client: AsyncClient):
    #Registering first time
    await client.post("/auth/register", json={
        "name": "Shop 2",
        "email": "duplicate@test.com",
        "password": "Pass456!",
    })

    response = await client.post("/auth/register", json={
        "name": "Shop 2 Duplicate",
        "email": "duplicate@test.com",
        "password": "Pass456!",
    })

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_login_returns_tokens(client: AsyncClient):
    #First registering
    await client.post("/auth/register", json={
        "name": "Login Test",
        "email": "login@test.com",
        "password": "TestPass123!",
    })

    #Login
    response = await client.post("/auth/token", json={
        "email": "login@test.com",
        "password": "TestPass123!",
    })

    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"



@pytest.mark.asyncio
async def test_login_wrong_password_returns_401(client: AsyncClient):
    await client.post("/auth/register", json={
        "name": "Test",
        "email": "wrongpass@test.com",
        "password": "CorrectPass!",
    })

    response = await client.post("/auth/token", json={
        "email": "wrongpass@test.com",
        "password": "WrongPass!",
    })


    assert response.status_code == 401


@pytest.mark.asyncio
async def test_tenant_isolation(client: AsyncClient, db_session: AsyncSession):
    """
    Two merchants must have diff schemas
    Checking that isolation works
    """
    resp1 = await client.post("/auth/register", json={
        "name": "Merchant A",
        "email": "merchant_a@test.com",
        "password": "Pass123!",
    })
    resp2 = await client.post("/auth/register", json={
        "name": "Merchant B",
        "email": "merchant_b@test.com",
        "password": "Pass456!",
    })

    schema_a = resp1.json()["schema_name"]
    schema_b = resp2.json()["schema_name"]


    #Schemas must be different
    assert schema_a != schema_b


    #Both schemas must exist in PostgreSQL
    for schema in [schema_a, schema_b]:
        result = await db_session.execute(
            text("SELECT schema_name FROM information_schema.schemata WHERE schema_name = :name"),
            {"name": schema},
        )
        assert result.scalar_one_or_none() is not None
        
