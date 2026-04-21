from unittest.mock import AsyncMock, MagicMock

import pytest

from app.infrastructure.redis.rate_limiter import SlidingWindowRateLimiter


@pytest.fixture
def patched_redis(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    # [ЧТО] Подменяем redis.from_url, чтобы не трогать реальный Redis в unit-тестах.
    # [ПОЧЕМУ] SlidingWindowRateLimiter всегда создаёт клиент в __init__.
    # [ОСТОРОЖНО] Если забыть патч — тесты зависят от локального Redis и становятся флейки.
    mock_redis = MagicMock()

    def _from_url(*_a: object, **_kw: object) -> MagicMock:
        return mock_redis

    monkeypatch.setattr(
        "app.infrastructure.redis.rate_limiter.aioredis.from_url",
        _from_url,
    )
    return mock_redis


@pytest.mark.asyncio
async def test_is_allowed_under_limit(patched_redis: MagicMock) -> None:
    pipe = MagicMock()
    pipe.__aenter__ = AsyncMock(return_value=pipe)
    pipe.__aexit__ = AsyncMock(return_value=None)
    pipe.zremrangebyscore = MagicMock(return_value=pipe)
    pipe.zcard = MagicMock(return_value=pipe)
    pipe.zadd = MagicMock(return_value=pipe)
    pipe.expire = MagicMock(return_value=pipe)
    pipe.execute = AsyncMock(return_value=[None, 3, None, None])
    patched_redis.pipeline = MagicMock(return_value=pipe)

    limiter = SlidingWindowRateLimiter()
    allowed, remaining = await limiter.is_allowed("m1", "free", "minute")
    assert allowed is True
    assert remaining == 100 - 3 - 1


@pytest.mark.asyncio
async def test_is_allowed_over_limit(patched_redis: MagicMock) -> None:
    pipe = MagicMock()
    pipe.__aenter__ = AsyncMock(return_value=pipe)
    pipe.__aexit__ = AsyncMock(return_value=None)
    pipe.zremrangebyscore = MagicMock(return_value=pipe)
    pipe.zcard = MagicMock(return_value=pipe)
    pipe.zadd = MagicMock(return_value=pipe)
    pipe.expire = MagicMock(return_value=pipe)
    pipe.execute = AsyncMock(return_value=[None, 100, None, None])
    patched_redis.pipeline = MagicMock(return_value=pipe)

    limiter = SlidingWindowRateLimiter()
    allowed, remaining = await limiter.is_allowed("m1", "free", "minute")
    assert allowed is False
    assert remaining == 0


@pytest.mark.asyncio
async def test_enterprise_unlimited(patched_redis: MagicMock) -> None:
    limiter = SlidingWindowRateLimiter()
    allowed, remaining = await limiter.is_allowed("m1", "enterprise", "minute")
    assert allowed is True
    assert remaining == 999999
    patched_redis.pipeline.assert_not_called()
