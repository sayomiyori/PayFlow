from typing import Any, cast

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db

router = APIRouter()
settings = get_settings()


@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """
    Health check endpoint.

    Проверяет что:
    1. Приложение запущено (факт что мы отвечаем)
    2. PostgreSQL доступен (SELECT 1 — самый лёгкий запрос)
    3. Redis доступен (ping)

    Kubernetes использует этот endpoint для liveness и readiness probe.
    Если возвращает не 200 — K8s перезапустит под.
    """
    checks: dict[str, str] = {}
    overall_status = "ok"

    # Check PostgreSQL
    try:
        await db.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as e:
        checks["postgres"] = f"error: {e}"
        overall_status = "degraded"

    # Check Redis
    try:
        redis_client = cast(
            Redis,
            aioredis.from_url(settings.redis_url),  # type: ignore[no-untyped-call]
        )
        await redis_client.ping()
        await redis_client.aclose()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"
        overall_status = "degraded"

    return {
        "status": overall_status,
        "checks": checks,
        "environment": settings.environment,
        "version": "0.1.0",
    }
