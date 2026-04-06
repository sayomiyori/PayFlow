import asyncio
import sys
from pathlib import Path

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

logger = structlog.get_logger()
PROJECT_ROOT = Path(__file__).resolve().parents[3]


def schema_name_from_merchant_id(merchant_id: str) -> str:
    return f"merchant_{merchant_id.replace('-', '')}"


async def create_tenant_schema(
    _db: AsyncSession,
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

    bind = _db.get_bind()
    url_obj = bind.url if hasattr(bind, "url") else bind.engine.url
    db_url = url_obj.render_as_string(hide_password=False)

    # Ensure schema exists before Alembic creates tenant-scoped version table.
    schema_engine = create_async_engine(db_url)
    async with schema_engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"'))
    await schema_engine.dispose()

    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "alembic",
        "-x",
        f"tenant_schema={schema_name}",
        "-x",
        f"db_url={db_url}",
        "upgrade",
        "head",
        cwd=str(PROJECT_ROOT),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(
            "Tenant migration failed: "
            f"{stderr.decode().strip() or stdout.decode().strip()}"
        )

    log.info("tenant_schema_created")


async def get_tenant_session(
    db: AsyncSession,
    merchant_id: str,
) -> AsyncSession:
    """
    "Switching" session on tanent schema

    After this call, all requests in this session use merchant-specific tables.

    Using:
        async with get_tenant_session(db, merchant.schema_name) as tenant_db:
            payments = await tenant_db.execute(select(Payment))
    """

    schema_name = schema_name_from_merchant_id(merchant_id)
    await db.execute(text(f"SET search_path TO {schema_name}, public"))
    return db
