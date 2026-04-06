from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import Boolean, DateTime, Enum, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class MerchantPlan(str, PyEnum):
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class Merchant(Base):
    """
    Tables of merchants live in public schema = its "shared" data
    Payments themselves are in merchant-specific schemas

    Mapped[type] its annotations SQLAlchemy 2.0 style
    They gives type hints and tells mypy checks types
    """

    __tablename__ = "merchants"
    __table_args__ = {"schema": "public"}

    id: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)

    # Password we store only like bcrypt hash = NEVER not plain text
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)

    # api key using for machine-to-machine authentication
    # (when merchant make queue from his backend`s)

    api_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)

    plan: Mapped[MerchantPlan] = mapped_column(
        Enum(MerchantPlan),
        default=MerchantPlan.FREE,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # schema_name: like "merchant_abc123"
    # For this name we create search_path

    schema_name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
