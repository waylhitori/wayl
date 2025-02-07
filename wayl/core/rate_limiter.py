from typing import Optional, Dict, List, Tuple
from redis import Redis
import time
import asyncio
from dataclasses import dataclass
import logging
from prometheus_client import Counter, Gauge
from fastapi import HTTPException, status

logger = logging.getLogger(__name__)

# Metrics
rate_limit_hits = Counter('rate_limit_hits_total', 'Total number of rate limit hits')
rate_limit_blocks = Counter('rate_limit_blocks_total', 'Total number of blocked requests')
active_limits = Gauge('rate_limit_active', 'Number of active rate limits')


@dataclass
class RateLimit:
    key: str
    limit: int
    window: int
    current: int
    reset_at: float


class RateLimiter:
    def __init__(
            self,
            redis_client: Optional[Redis] = None,
            prefix: str = "ratelimit"
    ):
        self.redis = redis_client
        self.prefix = prefix
        self._local_cache: Dict[str, Dict[float, int]] = {}
        self._lock = asyncio.Lock()

    async def check_rate_limit(
            self,
            key: str,
            limit: int,
            window: int = 60,
            cost: int = 1
    ) -> RateLimit:
        """
        Check if the request should be rate limited
        """
        try:
            rate_limit = await self._get_rate_limit(key, limit, window)

            if rate_limit.current + cost > limit:
                rate_limit_blocks.inc()
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail={
                        "error": "Rate limit exceeded",
                        "limit": limit,
                        "remaining": max(0, limit - rate_limit.current),
                        "reset_at": rate_limit.reset_at
                    }
                )

            await self._increment(key, cost, window)
            rate_limit_hits.inc()

            return rate_limit

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Rate limit check failed: {str(e)}")
            return RateLimit(key, limit, window, 0, time.time() + window)

    async def _get_rate_limit(
            self,
            key: str,
            limit: int,
            window: int
    ) -> RateLimit:
        """
        Get current rate limit status
        """
        current_time = time.time()
        full_key = f"{self.prefix}:{key}"

        if self.redis:
            return await self._get_redis_rate_limit(full_key, limit, window, current_time)
        else:
            return await self._get_local_rate_limit(full_key, limit, window, current_time)

    async def _get_redis_rate_limit(
            self,
            full_key: str,
            limit: int,
            window: int,
            current_time: float
    ) -> RateLimit:
        pipe = self.redis.pipeline()
        window_start = current_time - window

        # Clean old entries and get current count
        pipe.zremrangebyscore(full_key, '-inf', window_start)
        pipe.zcount(full_key, window_start, '+inf')
        pipe.zrange(full_key, 0, 0, withscores=True)

        results = await pipe.execute()
        current = int(results[1])
        oldest_request = results[2][0][1] if results[2] else current_time
        reset_at = oldest_request + window

        active_limits.set(current)

        return RateLimit(
            key=full_key,
            limit=limit,
            window=window,
            current=current,
            reset_at=reset_at
        )

    async def _get_local_rate_limit(
            self,
            full_key: str,
            limit: int,
            window: int,
            current_time: float
    ) -> RateLimit:
        async with self._lock:
            if full_key not in self._local_cache:
                self._local_cache[full_key] = {}

            window_start = current_time - window
            requests = self._local_cache[full_key]

            # Clean old entries
            expired = [ts for ts in requests if ts < window_start]
            for ts in expired:
                del requests[ts]

            current = sum(requests.values())
            oldest_request = min(requests.keys()) if requests else current_time
            reset_at = oldest_request + window

            active_limits.set(current)

            return RateLimit(
                key=full_key,
                limit=limit,
                window=window,
                current=current,
                reset_at=reset_at
            )

    async def _increment(
            self,
            key: str,
            cost: int,
            window: int
    ):
        """
        Increment the rate limit counter
        """
        current_time = time.time()
        full_key = f"{self.prefix}:{key}"

        if self.redis:
            await self.redis.zadd(full_key, {str(current_time): current_time})
            await self.redis.expire(full_key, window)
        else:
            async with self._lock:
                if full_key not in self._local_cache:
                    self._local_cache[full_key] = {}
                self._local_cache[full_key][current_time] = cost

    async def get_limit_status(
            self,
            key: str,
            limit: int,
            window: int = 60
    ) -> Dict:
        """
        Get current rate limit status without incrementing
        """
        rate_limit = await self._get_rate_limit(key, limit, window)
        return {
            "limit": rate_limit.limit,
            "remaining": max(0, limit - rate_limit.current),
            "reset_at": rate_limit.reset_at,
            "current": rate_limit.current
        }

    async def reset_limit(self, key: str):
        """
        Reset rate limit for a key
        """
        full_key = f"{self.prefix}:{key}"
        if self.redis:
            await self.redis.delete(full_key)
        else:
            async with self._lock:
                self._local_cache.pop(full_key, None)