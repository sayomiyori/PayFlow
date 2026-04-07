import hashlib
import hmac
import json
import os
import subprocess
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from testcontainers.postgres import PostgresContainer

from app.core.config import get_settings
from app.core.database import get_db
from app.main import app
from app.workers.reconciliation_worker import run_reconciliation


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


async def _register_and_create_payment(client: AsyncClient) -> tuple[str, str, dict]:
    email = f"webhooks_{uuid.uuid4().hex[:8]}@test.com"
    register = await client.post(
        "/auth/register",
        json={
            "name": "Webhook Tenant",
            "email": email,
            "password": "SecurePass123!",
            "plan": "free",
        },
    )
    assert register.status_code == 201
    schema_name = register.json()["schema_name"]
    merchant_id = register.json()["merchant_id"]

    token = await client.post(
        "/auth/token",
        json={"email": email, "password": "SecurePass123!"},
    )
    access_token = token.json()["access_token"]

    create_payment = await client.post(
        "/payments",
        json={"amount": "199.00", "currency": "RUB", "provider": "yukassa"},
        headers={
            "Authorization": f"Bearer {access_token}",
            "X-Idempotency-Key": f"idem-{uuid.uuid4().hex[:8]}",
        },
    )
    assert create_payment.status_code == 201
    return schema_name, merchant_id, create_payment.json()


def _make_signature(secret: str, payload: dict) -> str:
    raw = json.dumps(payload).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()


@pytest.mark.asyncio
async def test_webhook_invalid_signature(client: AsyncClient, db_session: AsyncSession):
    schema_name, merchant_id, payment = await _register_and_create_payment(client)
    event_payload = {
        "event_id": f"evt_{uuid.uuid4().hex}",
        "event_type": "payment.succeeded",
        "object": {
            "id": payment["provider_payment_id"],
            "status": "succeeded",
            "metadata": {"merchant_id": merchant_id},
        },
    }
    response = await client.post(
        "/webhooks/yukassa",
        content=json.dumps(event_payload),
        headers={"X-Webhook-Signature": "invalid-signature"},
    )
    assert response.status_code == 400

    await db_session.execute(text(f'SET search_path TO "{schema_name}", public'))
    failed_logs = await db_session.execute(
        text("SELECT COUNT(*) FROM webhook_log WHERE status = 'failed'")
    )
    assert int(failed_logs.scalar_one()) == 1


@pytest.mark.asyncio
async def test_webhook_duplicate(client: AsyncClient, db_session: AsyncSession):
    schema_name, merchant_id, payment = await _register_and_create_payment(client)
    event_id = f"evt_{uuid.uuid4().hex}"
    event_payload = {
        "event_id": event_id,
        "event_type": "payment.succeeded",
        "object": {
            "id": payment["provider_payment_id"],
            "status": "succeeded",
            "metadata": {"merchant_id": merchant_id},
        },
    }
    secret = get_settings().yukassa_webhook_secret
    signature = _make_signature(secret, event_payload)

    first = await client.post(
        "/webhooks/yukassa",
        content=json.dumps(event_payload),
        headers={"X-Webhook-Signature": signature},
    )
    second = await client.post(
        "/webhooks/yukassa",
        content=json.dumps(event_payload),
        headers={"X-Webhook-Signature": signature},
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["idempotent"] is True

    await db_session.execute(text(f'SET search_path TO "{schema_name}", public'))
    status_events = await db_session.execute(
        text("SELECT COUNT(*) FROM outbox WHERE event_type = 'payment.status_changed'")
    )
    assert int(status_events.scalar_one()) == 1


@pytest.mark.asyncio
async def test_reconciliation_fixes_stuck_payments(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    schema_name, merchant_id, payment = await _register_and_create_payment(client)
    await db_session.execute(text(f'SET search_path TO "{schema_name}", public'))
    await db_session.execute(
        text(
            "UPDATE payments "
            "SET status = 'processing', "
            "updated_at = :old_ts, "
            "metadata = jsonb_set(metadata, '{mock_provider_status}', '\"completed\"', true) "
            "WHERE provider_payment_id = :provider_payment_id"
        ),
        {
            "old_ts": datetime.now(UTC) - timedelta(minutes=11),
            "provider_payment_id": payment["provider_payment_id"],
        },
    )
    await db_session.commit()

    settings = get_settings()
    db_bind = db_session.get_bind()
    url_obj = db_bind.url if hasattr(db_bind, "url") else db_bind.engine.url
    db_url = url_obj.render_as_string(hide_password=False)
    monkeypatch.setattr(settings, "database_url", db_url)

    corrected = await run_reconciliation()
    assert corrected >= 1

    await db_session.execute(text(f'SET search_path TO "{schema_name}", public'))
    status_row = await db_session.execute(
        text(
            "SELECT status FROM payments WHERE provider_payment_id = :provider_payment_id"
        ),
        {"provider_payment_id": payment["provider_payment_id"]},
    )
    assert status_row.scalar_one() == "completed"
