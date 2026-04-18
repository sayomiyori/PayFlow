import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import (
    create_access_token,
    create_refresh_token,
    generate_api_key,
    hash_password,
    verify_password,
)
from app.infrastructure.db.models import Merchant, MerchantPlan
from app.infrastructure.db.tenant import create_tenant_schema

router = APIRouter(prefix="/auth", tags=["auth"])
logger = structlog.get_logger()

# Pydantic schema for validation incoming data
# FastAPI will automatically convert incoming data to this schema


class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str
    plan: MerchantPlan = MerchantPlan.FREE


class RegisterResponse(BaseModel):
    merchant_id: uuid.UUID
    api_key: str
    schema_name: str
    message: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    request: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> RegisterResponse:
    """
    Register a new merchant

    Process:
    1. Check if email is not taken
    2. Hashing password
    3. Generating API key and schema name
    4. Creating new entry for public.merchants
    5. Creating PostgreSQL schema for merchant
    6. All in one transaction - either everything works or nothing
    """

    log = logger.bind(email=request.email, plan=request.plan)

    # 1. Check if email is not taken
    existing = await db.execute(select(Merchant).where(Merchant.email == request.email))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    # Generating schema_name by UUID (without dashes for PostgreSQL)
    merchant_id = uuid.uuid4()
    schema_name = f"merchant_{str(merchant_id).replace('-', '')}"

    merchant = Merchant(
        id=str(merchant_id),
        name=request.name,
        email=request.email,
        hashed_password=hash_password(request.password),
        api_key=generate_api_key(),
        plan=request.plan,
        schema_name=schema_name,
    )

    db.add(merchant)

    # Creating schema before commit - if creating schema fails,
    # transaction will be rolled back and merchant will not be created
    await create_tenant_schema(db, schema_name)

    api_key = merchant.api_key

    # Fix transaction - and merchant, and schema will be created atomic
    await db.commit()

    log.info("merchant_registered", merchant_id=str(merchant_id))

    return RegisterResponse(
        merchant_id=merchant_id,
        api_key=api_key,
        schema_name=schema_name,
        message="Registration successful",
    )


@router.post(
    "/token",
    response_model=TokenResponse,
)
async def login(
    request: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """
    Taking JWT token

    Taking back tokens together immediatly
    - access token: for default requests (15 min)
    - refresh token: for refreshing access token (30 days)
    """
    result = await db.execute(select(Merchant).where(Merchant.email == request.email))
    merchant = result.scalar_one_or_none()

    # IMPORTANT: we dont disclose "user was not found" vs "wrong password"
    # Its prevents user enumeration attack
    if not merchant or not verify_password(request.password, merchant.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    if not merchant.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )

    token_data = {
        "sub": str(merchant.id),
        "schema": merchant.schema_name,
        "plan": merchant.plan.value,
    }

    return TokenResponse(
        access_token=create_access_token(token_data),
        refresh_token=create_refresh_token(token_data),
    )
