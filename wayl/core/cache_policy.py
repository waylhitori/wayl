from typing import Dict, Any, Optional
from enum import Enum
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class CacheStrategy(Enum):
    NONE = "none"
    SIMPLE = "simple"
    LRU = "lru"
    ADAPTIVE = "adaptive"


class CachePolicy:
    def __init__(
            self,
            strategy: CacheStrategy = CacheStrategy.ADAPTIVE,
            max_size: int = 1000,
            ttl_seconds: int = 3600,
            update_interval: int = 300
    ):
        self.strategy = strategy
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self.update_interval = update_interval
        self._last_update = datetime.utcnow()
        self._hit_counts: Dict[str, int] = {}
        self._access_times: Dict[str, datetime] = {}

    def should_cache(self, key: str, value: Any) -> bool:
        if self.strategy == CacheStrategy.NONE:
            return False

        if self.strategy == CacheStrategy.SIMPLE:
            return True

        current_time = datetime.utcnow()
        if (current_time - self._last_update).total_seconds() >= self.update_interval:
            self._update_statistics()

        if self.strategy == CacheStrategy.LRU:
            return len(self._access_times) < self.max_size

        if self.strategy == CacheStrategy.ADAPTIVE:
            hit_rate = self._hit_counts.get(key, 0) / max(1, len(self._access_times))
            return hit_rate > 0.1

    def update_access(self, key: str):
        current_time = datetime.utcnow()
        self._access_times[key] = current_time
        self._hit_counts[key] = self._hit_counts.get(key, 0) + 1

    def should_evict(self, key: str) -> bool:
        if key not in self._access_times:
            return False

        current_time = datetime.utcnow()
        age = (current_time - self._access_times[key]).total_seconds()

        if age > self.ttl_seconds:
            return True

        if self.strategy == CacheStrategy.LRU and len(self._access_times) >= self.max_size:
            oldest_key = min(self._access_times.items(), key=lambda x: x[1])[0]
            return key == oldest_key

        return False

    def _update_statistics(self):
        current_time = datetime.utcnow()
        self._last_update = current_time

        # Clean up old entries
        for key in list(self._access_times.keys()):
            if self.should_evict(key):
                del self._access_times[key]
                self._hit_counts.pop(key, None)

        # Decay hit counts
        for key in self._hit_counts:
            self._hit_counts[key] *= 0.95