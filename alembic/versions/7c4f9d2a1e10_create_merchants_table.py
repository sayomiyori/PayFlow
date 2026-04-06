"""create merchants table

Revision ID: 7c4f9d2a1e10
Revises: e0d0738a7d36
Create Date: 2026-04-06 15:35:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import context, op

# revision identifiers, used by Alembic.
revision: str = "7c4f9d2a1e10"
down_revision: str | None = "e0d0738a7d36"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


merchant_plan_enum = sa.Enum(
    "FREE",
    "PRO",
    "ENTERPRISE",
    name="merchantplan",
)


def upgrade() -> None:
    if context.get_x_argument(as_dictionary=True).get("tenant_schema"):
        return
    op.create_table(
        "merchants",
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("api_key", sa.String(length=255), nullable=False),
        sa.Column("plan", merchant_plan_enum, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("schema_name", sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("api_key"),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("schema_name"),
        schema="public",
    )


def downgrade() -> None:
    if context.get_x_argument(as_dictionary=True).get("tenant_schema"):
        return
    op.drop_table("merchants", schema="public")
    merchant_plan_enum.drop(op.get_bind(), checkfirst=True)
