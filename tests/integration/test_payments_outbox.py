import os
import subprocess
import uuid

import pytest
import pytest_asyncio
from aiokafka.errors import KafkaConnectionError, KafkaTimeoutError
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from testcontainers.kafka import KafkaContainer
from testcontainers.postgres import PostgresContainer

from app.core.config import get_settings
from app.core.database import get_db
from app.main import app
from app.workers.outbox_worker import process_outbox_batch


def _to_asyncpg_url(sync_url: str) -> str:
    if sync_url.startswith("postgresql+psycopg2://"):
        return sync_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
    return sync_url.replace("postgresql://", "postgresql+asyncpg://", 1)


@pytest.fixture(scope="module")
def postgres_container() -> PostgresContainer:
    container = PostgresContainer("postgres:16-alpine", dbname="payflow_test")
    container.start()
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="module")
def kafka_container() -> KafkaContainer:
    container = KafkaContainer("confluentinc/cp-kafka:7.6.1")
    container.start()
    try:
        yield container
    finally:
        container.stop()


@pytest_asyncio.fixture(scope="module")
async def test_engine(postgres_container: PostgresContainer):
    sync_url = postgres_container.get_connection_url()
    async_url = _to_asyncpg_url(sync_url)
    engine = create_async_engine(async_url, poolclass=NullPool)

    env = os.environ.copy()
    env["DATABASE_URL"] = async_url
    env["DATABASE_URL_SYNC"] = sync_url
    subprocess.run(
        ["alembic", "-x", f"db_url={async_url}", "upgrade", "head"],
        check=True,
        cwd="/mnt/d/Programming/PayFlow",
        env=env,
    )

    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine):
    async with async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac
    app.dependency_overrides.clear()


async def _register_and_get_token(client: AsyncClient, email: str) -> tuple[str, str]:
    register = await client.post(
        "/auth/register",
        json={
            "name": "Tenant",
            "email": email,
            "password": "SecurePass123!",
            "plan": "free",
        },
    )
    assert register.status_code == 201
    schema_name = register.json()["schema_name"]

    token = await client.post(
        "/auth/token",
        json={"email": email, "password": "SecurePass123!"},
    )
    assert token.status_code == 200
    access_token = token.json()["access_token"]
    return schema_name, access_token


@pytest.mark.asyncio
async def test_payment_idempotency(client: AsyncClient, db_session: AsyncSession):
    schema_name, access_token = await _register_and_get_token(
        client, f"idempotency_{uuid.uuid4().hex[:8]}@test.com"
    )
    headers = {
        "Authorization": f"Bearer {access_token}",
        "X-Idempotency-Key": "idem-constant-key",
    }
    body = {"amount": "100.00", "currency": "RUB", "provider": "yukassa"}

    first = await client.post("/payments", json=body, headers=headers)
    second = await client.post("/payments", json=body, headers=headers)
    third = await client.post("/payments", json=body, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 200
    assert third.status_code == 200

    await db_session.execute(text(f'SET search_path TO "{schema_name}", public'))
    rs = await db_session.execute(text("SELECT COUNT(*) FROM payments"))
    assert int(rs.scalar_one()) == 1


@pytest.mark.asyncio
async def test_outbox_atomicity(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    schema_name, access_token = await _register_and_get_token(
        client, f"atomicity_{uuid.uuid4().hex[:8]}@test.com"
    )
    headers = {
        "Authorization": f"Bearer {access_token}",
        "X-Idempotency-Key": f"idem-{uuid.uuid4().hex[:8]}",
    }
    body = {"amount": "50.00", "currency": "RUB", "provider": "yukassa"}
    create = await client.post("/payments", json=body, headers=headers)
    assert create.status_code == 201

    settings = get_settings()
    monkeypatch.setattr(settings, "kafka_bootstrap_servers", "localhost:1")
    with pytest.raises((KafkaConnectionError, KafkaTimeoutError, OSError)):
        await process_outbox_batch()

    await db_session.execute(text(f'SET search_path TO "{schema_name}", public'))
    payment_count = await db_session.execute(text("SELECT COUNT(*) FROM payments"))
    outbox_pending = await db_session.execute(
        text("SELECT COUNT(*) FROM outbox WHERE processed = FALSE")
    )
    assert int(payment_count.scalar_one()) == 1
    assert int(outbox_pending.scalar_one()) >= 1


@pytest.mark.asyncio
async def test_outbox_worker(
    client: AsyncClient,
    db_session: AsyncSession,
    kafka_container: KafkaContainer,
    monkeypatch: pytest.MonkeyPatch,
):
    schema_name, access_token = await _register_and_get_token(
        client, f"worker_{uuid.uuid4().hex[:8]}@test.com"
    )
    headers = {
        "Authorization": f"Bearer {access_token}",
        "X-Idempotency-Key": f"idem-{uuid.uuid4().hex[:8]}",
    }
    body = {"amount": "10.00", "currency": "RUB", "provider": "yukassa"}

    for _ in range(3):
        headers["X-Idempotency-Key"] = f"idem-{uuid.uuid4().hex[:8]}"
        created = await client.post("/payments", json=body, headers=headers)
        assert created.status_code == 201

    settings = get_settings()
    db_bind = db_session.get_bind()
    url_obj = db_bind.url if hasattr(db_bind, "url") else db_bind.engine.url
    db_url = url_obj.render_as_string(hide_password=False)
    monkeypatch.setattr(settings, "database_url", db_url)
    monkeypatch.setattr(
        settings, "kafka_bootstrap_servers", kafka_container.get_bootstrap_server()
    )

    published = await process_outbox_batch()
    assert published >= 3

    await db_session.execute(text(f'SET search_path TO "{schema_name}", public'))
    pending = await db_session.execute(
        text("SELECT COUNT(*) FROM outbox WHERE processed = FALSE")
    )
    assert int(pending.scalar_one()) == 0
