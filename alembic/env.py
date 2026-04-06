import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

# import all models - Alembic needs to know about all tables
from alembic import context
from app.core.config import get_settings
from app.core.database import Base

config = context.config
settings = get_settings()
x_args = context.get_x_argument(as_dictionary=True)
db_url = x_args.get("db_url") or settings.database_url

config.set_main_option("sqlalchemy.url", db_url)
tenant_schema = x_args.get("tenant_schema")

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Migrations without real connection to DB - generating SQL files"""

    url = config.get_main_option("sqlalchemy.url")
    kwargs = {
        "url": url,
        "target_metadata": target_metadata,
        "literal_binds": True,
        "dialect_opts": {"paramstyle": "named"},
    }
    if tenant_schema:
        kwargs["version_table_schema"] = tenant_schema
    context.configure(
        **kwargs,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    kwargs = {"connection": connection, "target_metadata": target_metadata}
    if tenant_schema:
        kwargs["version_table_schema"] = tenant_schema
    context.configure(**kwargs)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Async migrations - real connection through asyncpg"""

    connectable = create_async_engine(db_url, poolclass=pool.NullPool)

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
