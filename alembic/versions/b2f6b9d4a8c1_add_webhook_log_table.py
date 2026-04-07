"""add webhook log table

Revision ID: b2f6b9d4a8c1
Revises: 9a51b3c22f10
Create Date: 2026-04-06 17:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import context, op

revision: str = "b2f6b9d4a8c1"
down_revision: str | None = "9a51b3c22f10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _get_tenant_schema() -> str | None:
    return context.get_x_argument(as_dictionary=True).get("tenant_schema")


def upgrade() -> None:
    tenant_schema = _get_tenant_schema()
    if not tenant_schema:
        return

    op.create_table(
        "webhook_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "signature_valid", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("processed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default=sa.text("'received'")
        ),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id"),
        schema=tenant_schema,
    )

    op.create_index(
        "ix_webhook_log_status",
        "webhook_log",
        ["status", "received_at"],
        unique=False,
        schema=tenant_schema,
    )


def downgrade() -> None:
    tenant_schema = _get_tenant_schema()
    if not tenant_schema:
        return

    op.drop_index("ix_webhook_log_status", table_name="webhook_log", schema=tenant_schema)
    op.drop_table("webhook_log", schema=tenant_schema)
