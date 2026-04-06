import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


async def create_tenant_schema(
    db: AsyncSession,
    schema_name: str,
) -> None:
    """
    Creating PostgreSQL schema for a new merchant

    Each merchant taking name like: merchant_<uuid_without_dashes>
    For example: merchant_550e8400e29b41d4a716446655440000

    Inside schema we create tables: payments, outbox, webhook_log.
    Its working in Alembic migrations with installed search_path
    """
    log = logger.bind(schema_name=schema_name)
    log.info("creating_tenant_schema")

    # CREATE SCHEMA IF NOT EXISTS - idempotent operation
    # (u can call it many times without errors)
    await db.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema_name}"))

    # Creating base tables inside new schema
    # Installing search_path for CREATE TABLE to create tables in necessary schema
    await db.execute(text(f"SET search_path TO {schema_name}"))

    # Payment table
    await db.execute(
        text("""
        CREATE TABLE IF NOT EXISTS payments (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            amount NUMERIC(12, 2) NOT NULL,
            currency VARCHAR(3) NOT NULL DEFAULT 'RUB',
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            idempotency_key VARCHAR(255) UNIQUE,
            provider VARCHAR(20) NOT NULL DEFAULT 'yukassa',
            provider_payment_id VARCHAR(255),
            metadata JSONB DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    )

    # Outbox table - main for Outbox Patter (Phase 3)
    await db.execute(
        text("""
        CREATE TABLE IF NOT EXISTS outbox (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        event_type VARCHAR(100) NOT NULL,
        aggregate_id UUID NOT NULL,
        payload JSONB NOT NULL,
        processed BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        processed_at TIMESTAMPTZ
        )
    """)
    )

    # Index for fast search unreading records
    # Outbox worker reading WHERE processed = FALSE
    await db.execute(
        text("""
        CREATE INDEX IF NOT EXISTS idx_outbox_unprocessed
        ON outbox (created_at)
        WHERE processed = FALSE
    """)
    )

    # Taking back search_path in public
    await db.execute(text("SET search_path to public"))

    log.info("tenant_schema_created")


async def get_tenant_session(
    db: AsyncSession,
    schema_name: str,
) -> AsyncSession:
    """
    "Switching" session on tanent schema

    After this call, all requests in this session use merchant-specific tables.

    Using:
        async with get_tenant_session(db, merchant.schema_name) as tenant_db:
            payments = await tenant_db.execute(select(Payment))
    """

    await db.execute(text(f"SET search_path TO {schema_name}, public"))
    return db
