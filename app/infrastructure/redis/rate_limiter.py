import time

import redis.asyncio as aioredis

from app.core.config import get_settings

settings = get_settings()

# Limits for plans: {plan: (requests_per_minute, requests_per_day)}
PLAN_LIMITS = {
    "free": (100, 1_000),
    "pro": (1_000, 50_000),
    "enterprise": (None, None),
}


class SlidingWindowRateLimiter:
    """
    Sliding Window Rate Limiter on base Redis ZSET (Sorted Set)

    Algorithm:
    1. Key in Redis = "rate:{merchant_id}:{window}"
    2. In ZSET we store timestamp each request
    3. By each request:
        a. Deleting signatures older than window_seconds (ZREMRANGEBYSCORE)
        b. Counting total requests in ZSET (ZCARD)
        c. If count >= limit -> blocking
        d. If count < limit -> adding current timestamp (ZADD)


    Why "sliding" but not "fixed"?
    Fixed window: resets each minute evenly
    Problem: end of one minute + start of the next can allow a burst.

    Sliding window always evaluates the previous N seconds from now.
    Not "boundary exploit"
    """

    def __init__(self):
        self.redis = aioredis.from_url(settings.redis_url, decode_responses=True)

    async def is_allowed(
        self,
        merchant_id: str,
        plan: str,
        window: str = "minute",
    ) -> tuple[bool, int]:
        """
        Проверяет разрешён ли запрос.

        Returns:
            (allowed: bool, requests_remaining: int)
        """

        per_minute, per_day = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])

        if window == "minute":
            limit = per_minute
            window_seconds = 60
        else:
            limit = per_day
            window_seconds = 86400

        if limit is None:
            return True, 999999  # Enterprise — без ограничений

        key = f"rate:{merchant_id}:{window}"
        now = time.time()
        window_start = now - window_seconds

        # Using Redis pipeline for atomic execution
        # All commands in one operation(protection for race condition)
        async with self.redis.pipeline() as pipe:
            # Deleting old requests (ZREMRANGEBYSCORE)
            pipe.zremrangebyscore(key, "-inf", window_start)
            # Counting requests in ZSET (ZCARD)
            pipe.zcard(key)
            # Adding current request (ZADD)
            pipe.zadd(key, {str(now): now})
            # Installing TTL for key automatically deleting
            pipe.expire(key, window_seconds * 2)

            results = await pipe.execute()

        current_count = results[1]

        if current_count >= limit:
            return False, 0

        return True, limit - current_count - 1

    async def close(self):
        await self.redis.aclose()
