"""create tenant tables

Revision ID: 9a51b3c22f10
Revises: 7c4f9d2a1e10
Create Date: 2026-04-06 16:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import context, op

# revision identifiers, used by Alembic.
revision: str = "9a51b3c22f10"
down_revision: str | None = "7c4f9d2a1e10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _get_tenant_schema() -> str | None:
    return context.get_x_argument(as_dictionary=True).get("tenant_schema")


def upgrade() -> None:
    tenant_schema = _get_tenant_schema()
    if not tenant_schema:
        return

    op.execute(sa.text(f'CREATE SCHEMA IF NOT EXISTS "{tenant_schema}"'))

    op.create_table(
        "payments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "currency", sa.String(length=3), nullable=False, server_default="RUB"
        ),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="pending"
        ),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column(
            "provider", sa.String(length=20), nullable=False, server_default="yukassa"
        ),
        sa.Column("provider_payment_id", sa.String(length=255), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
        schema=tenant_schema,
    )

    op.create_table(
        "webhooks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=tenant_schema,
    )

    op.create_table(
        "events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("aggregate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "processed", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        schema=tenant_schema,
    )

    op.create_index(
        "ix_events_unprocessed",
        "events",
        ["created_at"],
        unique=False,
        schema=tenant_schema,
        postgresql_where=sa.text("processed = false"),
    )


def downgrade() -> None:
    tenant_schema = _get_tenant_schema()
    if not tenant_schema:
        return

    op.drop_index("ix_events_unprocessed", table_name="events", schema=tenant_schema)
    op.drop_table("events", schema=tenant_schema)
    op.drop_table("webhooks", schema=tenant_schema)
    op.drop_table("payments", schema=tenant_schema)
