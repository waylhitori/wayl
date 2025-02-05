from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from redis import Redis
import time
import json
from ..config.settings import settings
import logging

logger = logging.getLogger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, redis_client: Redis):
        super().__init__(app)
        self.redis = redis_client

    async def dispatch(self, request: Request, call_next):
        try:
            # Get user token level from auth header
            token = request.headers.get("Authorization", "").split(" ")[1]
            user_info = await self.get_user_info(token)
            rate_limit = user_info.get("rate_limit", settings.DEFAULT_RATE_LIMIT)

            # Rate limit key includes user ID for per-user limiting
            key = f"rate_limit:{user_info['id']}:{int(time.time() // settings.RATE_LIMIT_WINDOW)}"

            # Use Redis pipeline for atomic operations
            pipe = self.redis.pipeline()
            pipe.incr(key)
            pipe.expire(key, settings.RATE_LIMIT_WINDOW)
            current, _ = pipe.execute()

            if current > rate_limit:
                logger.warning(f"Rate limit exceeded for user {user_info['id']}")
                raise HTTPException(
                    status_code=429,
                    detail={
                        "error": "Rate limit exceeded",
                        "limit": rate_limit,
                        "window_seconds": settings.RATE_LIMIT_WINDOW,
                        "reset_after": self.redis.ttl(key)
                    }
                )

            # Add rate limit headers
            response = await call_next(request)
            response.headers["X-RateLimit-Limit"] = str(rate_limit)
            response.headers["X-RateLimit-Remaining"] = str(rate_limit - current)
            response.headers["X-RateLimit-Reset"] = str(self.redis.ttl(key))

            return response

        except Exception as e:
            logger.error(f"Rate limiting error: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail="Internal server error during rate limiting"
            )

    async def get_user_info(self, token: str) -> dict:
        """Get user info from Redis cache or database"""
        key = f"user_info:{token}"
        user_info = self.redis.get(key)

        if user_info:
            return json.loads(user_info)

        # If not in cache, get from database and cache it
        try:
            from ..db.crud import get_user_by_token
            user = await get_user_by_token(token)
            user_info = {
                "id": str(user.id),
                "rate_limit": user.token_benefits.get("api_rate_limit", settings.DEFAULT_RATE_LIMIT)
            }
            self.redis.setex(
                key,
                settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
                json.dumps(user_info)
            )
            return user_info
        except Exception as e:
            logger.error(f"Error getting user info: {str(e)}")
            return {"id": "anonymous", "rate_limit": settings.DEFAULT_RATE_LIMIT}


class SecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # Security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = "default-src 'self'"

        return response


class PrometheusMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        from prometheus_client import Counter, Histogram

        self.requests_total = Counter(
            'http_requests_total',
            'Total HTTP requests',
            ['method', 'endpoint', 'status_code']
        )

        self.requests_duration = Histogram(
            'http_request_duration_seconds',
            'HTTP request duration',
            ['method', 'endpoint']
        )

    async def dispatch(self, request: Request, call_next):
        start_time = time.time()

        response = await call_next(request)

        duration = time.time() - start_time
        self.requests_total.labels(
            method=request.method,
            endpoint=request.url.path,
            status_code=response.status_code
        ).inc()

        self.requests_duration.labels(
            method=request.method,
            endpoint=request.url.path
        ).observe(duration)

        return response