from typing import Any, Dict, Optional, List, Union
from redis import Redis
from datetime import datetime, timedelta
import json
import asyncio
import logging
from prometheus_client import Counter, Histogram
import hashlib
import pickle
from functools import wraps

logger = logging.getLogger(__name__)

# Metrics
cache_hits = Counter('cache_hits_total', 'Total number of cache hits')
cache_misses = Counter('cache_misses_total', 'Total number of cache misses')
cache_operation_time = Histogram('cache_operation_seconds', 'Cache operation time')


class CacheManager:
    def __init__(
            self,
            redis_client: Optional[Redis] = None,
            default_ttl: int = 3600,
            prefix: str = "cache"
    ):
        self.redis = redis_client
        self.default_ttl = default_ttl
        self.prefix = prefix
        self._local_cache: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def get(
            self,
            key: str,
            default: Any = None
    ) -> Any:
        full_key = f"{self.prefix}:{key}"

        try:
            if self.redis:
                cached = await self.redis.get(full_key)
                if cached:
                    cache_hits.inc()
                    return self._deserialize(cached)
            else:
                async with self._lock:
                    if full_key in self._local_cache:
                        cache_data = self._local_cache[full_key]
                        if self._is_valid(cache_data):
                            cache_hits.inc()
                            return cache_data['value']
                        else:
                            del self._local_cache[full_key]

            cache_misses.inc()
            return default

        except Exception as e:
            logger.error(f"Cache get error: {str(e)}")
            return default

    async def set(
            self,
            key: str,
            value: Any,
            ttl: Optional[int] = None,
            tags: Optional[List[str]] = None
    ):
        full_key = f"{self.prefix}:{key}"
        ttl = ttl or self.default_ttl

        try:
            if self.redis:
                serialized = self._serialize(value)
                pipe = self.redis.pipeline()
                pipe.set(full_key, serialized, ex=ttl)

                if tags:
                    for tag in tags:
                        pipe.sadd(f"{self.prefix}:tag:{tag}", full_key)
                        pipe.expire(f"{self.prefix}:tag:{tag}", ttl)

                await pipe.execute()
            else:
                async with self._lock:
                    self._local_cache[full_key] = {
                        'value': value,
                        'expires_at': datetime.utcnow() + timedelta(seconds=ttl),
                        'tags': tags or []
                    }

        except Exception as e:
            logger.error(f"Cache set error: {str(e)}")

    async def delete(self, key: str):
        full_key = f"{self.prefix}:{key}"

        try:
            if self.redis:
                await self.redis.delete(full_key)
            else:
                async with self._lock:
                    self._local_cache.pop(full_key, None)

        except Exception as e:
            logger.error(f"Cache delete error: {str(e)}")

    async def delete_by_tag(self, tag: str):
        try:
            if self.redis:
                tag_key = f"{self.prefix}:tag:{tag}"
                keys = await self.redis.smembers(tag_key)
                if keys:
                    pipe = self.redis.pipeline()
                    pipe.delete(*keys)
                    pipe.delete(tag_key)
                    await pipe.execute()
            else:
                async with self._lock:
                    keys_to_delete = [
                        k for k, v in self._local_cache.items()
                        if tag in v.get('tags', [])
                    ]
                    for k in keys_to_delete:
                        del self._local_cache[k]

        except Exception as e:
            logger.error(f"Cache delete by tag error: {str(e)}")

    async def clear(self, pattern: str = "*"):
        try:
            if self.redis:
                keys = await self.redis.keys(f"{self.prefix}:{pattern}")
                if keys:
                    await self.redis.delete(*keys)
            else:
                async with self._lock:
                    self._local_cache.clear()

        except Exception as e:
            logger.error(f"Cache clear error: {str(e)}")

    def cached(
            self,
            ttl: Optional[int] = None,
            key_prefix: Optional[str] = None,
            tags: Optional[List[str]] = None
    ):
        def decorator(func):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                cache_key = self._generate_cache_key(
                    func.__name__,
                    key_prefix,
                    args,
                    kwargs
                )

                cached_value = await self.get(cache_key)
                if cached_value is not None:
                    return cached_value

                result = await func(*args, **kwargs)
                await self.set(cache_key, result, ttl, tags)
                return result

            return wrapper

        return decorator

    def _serialize(self, value: Any) -> bytes:
        try:
            return pickle.dumps(value)
        except Exception:
            return json.dumps(value).encode('utf-8')

    def _deserialize(self, value: bytes) -> Any:
        try:
            return pickle.loads(value)
        except Exception:
            return json.loads(value.decode('utf-8'))

    def _is_valid(self, cache_data: Dict) -> bool:
        return datetime.utcnow() < cache_data['expires_at']

    def _generate_cache_key(
            self,
            func_name: str,
            prefix: Optional[str],
            args: tuple,
            kwargs: dict
    ) -> str:
        key_parts = [prefix] if prefix else []
        key_parts.append(func_name)

        if args:
            key_parts.append(self._hash_args(args))
        if kwargs:
            key_parts.append(self._hash_args(kwargs))

        return ":".join(key_parts)

    def _hash_args(self, args: Union[tuple, dict]) -> str:
        return hashlib.sha256(
            str(sorted(str(args).items()) if isinstance(args, dict) else str(args)).encode()
        ).hexdigest()[:16]