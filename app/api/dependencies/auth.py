from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_token
from app.infrastructure.db.models import Merchant
from app.infrastructure.db.tenant import get_tenant_session
from app.infrastructure.redis.rate_limiter import SlidingWindowRateLimiter

security = HTTPBearer()
rate_limiter = SlidingWindowRateLimiter()


async def get_current_merchant(
    credentials: HTTPAuthorizationCredentials = Security(security),
    db: AsyncSession = Depends(get_db),
) -> Merchant:
    """
    FastAPI dependency - getting current merchant from JWT token

    Using:
        @router.get("/payments)
        async def get_payments(
            merchant: Merchant = Depends(get_current_merchant),
        ):
            ...

    FastAPI automatically reads Authorization header into credentials.
    If token is invalid, endpoint returns 401 before handler execution.
    """
    try:
        payload = decode_token(credentials.credentials)
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from err

    merchant_id = payload.get("sub")
    if not merchant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    result = await db.execute(select(Merchant).where(Merchant.id == merchant_id))
    merchant = result.scalar_one_or_none()

    if not merchant or not merchant.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Merchant not found or deactivated",
        )

    return merchant


async def check_rate_limit(
    merchant: Merchant = Depends(get_current_merchant),
):
    """
    Dependency for rate limiting
    Checking limits per minute

    Add to endpoints that should be rate limited:
        @router.post("/payments", dependencies=[Depends(check_rate_limit)])
    """
    allowed, remaining = await rate_limiter.is_allowed(
        merchant_id=str(merchant.id),
        plan=merchant.plan.value,
        window="minute",
    )

    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
            headers={
                "X-RateLimit-Remaining": "0",
                "Retry-After": "60",
            },
        )

    return merchant


async def inject_tenant(
    merchant: Merchant = Depends(get_current_merchant),
    db: AsyncSession = Depends(get_db),
) -> AsyncSession:
    return await get_tenant_session(db, str(merchant.id))
