from typing import Optional, Dict, Callable, Any
from enum import Enum
import time
import asyncio
import logging
from prometheus_client import Counter, Gauge
from redis import Redis
import json
from datetime import datetime

logger = logging.getLogger(__name__)

# Metrics
circuit_state = Gauge('circuit_breaker_state', 'Circuit breaker state', ['service'])
failure_count = Counter('circuit_breaker_failures', 'Circuit breaker failures', ['service'])
success_count = Counter('circuit_breaker_successes', 'Circuit breaker successes', ['service'])


class CircuitState(Enum):
    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Service is down
    HALF_OPEN = "half_open"  # Testing if service is back


class CircuitBreaker:
    def __init__(
            self,
            redis_client: Optional[Redis] = None,
            failure_threshold: int = 5,
            reset_timeout: int = 60,
            half_open_timeout: int = 30,
            prefix: str = "circuit"
    ):
        self.redis = redis_client
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.half_open_timeout = half_open_timeout
        self.prefix = prefix
        self._local_state: Dict[str, Dict] = {}
        self._lock = asyncio.Lock()

    async def call(
            self,
            service: str,
            func: Callable,
            fallback: Optional[Callable] = None,
            *args,
            **kwargs
    ) -> Any:
        state = await self.get_state(service)

        if state == CircuitState.OPEN:
            if await self._should_attempt_reset(service):
                await self._set_state(service, CircuitState.HALF_OPEN)
            else:
                return await self._handle_open_circuit(service, fallback, *args, **kwargs)

        try:
            result = await func(*args, **kwargs)
            await self._handle_success(service)
            return result

        except Exception as e:
            await self._handle_failure(service)
            if fallback:
                return await fallback(*args, **kwargs)
            raise

    async def get_state(self, service: str) -> CircuitState:
        try:
            if self.redis:
                state_data = await self.redis.get(f"{self.prefix}:{service}")
                if state_data:
                    return CircuitState(json.loads(state_data)['state'])
            else:
                async with self._lock:
                    if service in self._local_state:
                        return CircuitState(self._local_state[service]['state'])

            return CircuitState.CLOSED

        except Exception as e:
            logger.error(f"Failed to get circuit state: {str(e)}")
            return CircuitState.CLOSED

    async def _set_state(
            self,
            service: str,
            state: CircuitState,
            failures: int = 0
    ):
        state_data = {
            'state': state.value,
            'last_failure': datetime.utcnow().isoformat(),
            'failures': failures,
            'updated_at': datetime.utcnow().isoformat()
        }

        try:
            if self.redis:
                await self.redis.set(
                    f"{self.prefix}:{service}",
                    json.dumps(state_data)
                )
            else:
                async with self._lock:
                    self._local_state[service] = state_data

            circuit_state.labels(service=service).set(
                1 if state == CircuitState.CLOSED else 0
            )

        except Exception as e:
            logger.error(f"Failed to set circuit state: {str(e)}")

    async def _handle_success(self, service: str):
        if await self.get_state(service) == CircuitState.HALF_OPEN:
            await self._set_state(service, CircuitState.CLOSED)

        success_count.labels(service=service).inc()

    async def _handle_failure(self, service: str):
        failure_count.labels(service=service).inc()

        current_state = await self.get_state(service)
        if current_state == CircuitState.CLOSED:
            failures = await self._increment_failures(service)
            if failures >= self.failure_threshold:
                await self._set_state(service, CircuitState.OPEN)
        elif current_state == CircuitState.HALF_OPEN:
            await self._set_state(service, CircuitState.OPEN)

    async def _increment_failures(self, service: str) -> int:
        try:
            if self.redis:
                key = f"{self.prefix}:failures:{service}"
                current = await self.redis.incr(key)
                await self.redis.expire(key, self.reset_timeout)
                return current
            else:
                async with self._lock:
                    state = self._local_state.get(service, {'failures': 0})
                    failures = state.get('failures', 0) + 1
                    state['failures'] = failures
                    self._local_state[service] = state
                    return failures

        except Exception as e:
            logger.error(f"Failed to increment failures: {str(e)}")
            return 0

    async def _should_attempt_reset(self, service: str) -> bool:
        try:
            state_data = None
            if self.redis:
                data = await self.redis.get(f"{self.prefix}:{service}")
                if data:
                    state_data = json.loads(data)
            else:
                async with self._lock:
                    state_data = self._local_state.get(service)

            if not state_data:
                return True

            last_failure = datetime.fromisoformat(state_data['last_failure'])
            elapsed = (datetime.utcnow() - last_failure).total_seconds()

            return elapsed >= self.reset_timeout

        except Exception as e:
            logger.error(f"Failed to check reset timeout: {str(e)}")
            return True

    async def _handle_open_circuit(
            self,
            service: str,
            fallback: Optional[Callable],
            *args,
            **kwargs
    ) -> Any:
        if fallback:
            return await fallback(*args, **kwargs)

        raise Exception(f"Circuit breaker is open for service: {service}")

    async def reset(self, service: str):
        """Manually reset circuit breaker state"""
        await self._set_state(service, CircuitState.CLOSED)

    async def force_open(self, service: str):
        """Manually force circuit breaker to open state"""
        await self._set_state(service, CircuitState.OPEN)