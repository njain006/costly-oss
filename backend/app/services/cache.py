from datetime import datetime
import time
import json
import threading
from typing import Optional, Any

from app.config import settings


class _InMemoryCache:
    """Fallback in-memory TTL cache."""

    def __init__(self):
        self._store = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._store.get(key)
            if entry:
                val, exp = entry
                if time.time() < exp:
                    return val
                del self._store[key]
        return None

    def set(self, key: str, val: Any, ttl: int):
        with self._lock:
            self._store[key] = (val, time.time() + ttl)

    def delete(self, key: str):
        with self._lock:
            self._store.pop(key, None)

    def clear_prefix(self, prefix: str):
        with self._lock:
            to_del = [k for k in self._store if k.startswith(prefix)]
            for k in to_del:
                del self._store[k]


class _RedisCache:
    """Redis-backed cache with JSON serialization."""

    def __init__(self):
        import redis
        self._redis = redis.from_url(settings.redis_url, decode_responses=True)
        self._fallback = _InMemoryCache()
        self._available = True
        try:
            self._redis.ping()
        except Exception:
            print("[CACHE] Redis not available, falling back to in-memory cache")
            self._available = False

    def get(self, key: str) -> Optional[Any]:
        if not self._available:
            return self._fallback.get(key)
        try:
            raw = self._redis.get(f"costly:{key}")
            if raw is not None:
                return json.loads(raw)
            return None
        except Exception:
            return self._fallback.get(key)

    def set(self, key: str, val: Any, ttl: int):
        if not self._available:
            self._fallback.set(key, val, ttl)
            return
        try:
            self._redis.setex(f"costly:{key}", ttl, json.dumps(val, default=str))
        except Exception:
            self._fallback.set(key, val, ttl)

    def delete(self, key: str):
        if not self._available:
            self._fallback.delete(key)
            return
        try:
            self._redis.delete(f"costly:{key}")
        except Exception:
            self._fallback.delete(key)

    def clear_prefix(self, prefix: str):
        if not self._available:
            self._fallback.clear_prefix(prefix)
            return
        try:
            keys = self._redis.keys(f"costly:{prefix}*")
            if keys:
                self._redis.delete(*keys)
        except Exception:
            self._fallback.clear_prefix(prefix)


def _create_cache():
    try:
        return _RedisCache()
    except Exception:
        print("[CACHE] Redis import failed, using in-memory cache")
        return _InMemoryCache()


class _StaleFallback:
    """Serve the last good result when the fresh one has expired.

    Only keys that a background job explicitly saved a long-lived copy for
    (``set_with_stale``) ever fall back, so ordinary cache entries behave
    exactly as before. ``delete`` (the refresh button) drops both copies, so
    a manual refresh always recomputes."""

    STALE_PREFIX = "stale:"

    def __init__(self, inner):
        self._inner = inner

    def get(self, key: str):
        val = self._inner.get(key)
        if val is None:
            val = self._inner.get(self.STALE_PREFIX + key)
            if isinstance(val, dict):
                # Older than its normal TTL: say so instead of passing it off
                # as fresh. Routers report computed_at as fetched_at.
                val = {**val, "stale": True}
        return val

    @staticmethod
    def _stamp(val):
        # Remember when a page was computed, so a cached copy reports its
        # real age rather than the time it was served.
        if isinstance(val, dict) and "computed_at" not in val:
            return {**val, "computed_at": datetime.utcnow().isoformat()}
        return val

    def set(self, key: str, val, ttl: int):
        self._inner.set(key, self._stamp(val), ttl)

    def set_with_stale(self, key: str, val, ttl: int, stale_ttl: int = 7 * 86400):
        val = self._stamp(val)
        self._inner.set(key, val, ttl)
        self._inner.set(self.STALE_PREFIX + key, val, stale_ttl)

    def delete(self, key: str):
        self._inner.delete(key)
        self._inner.delete(self.STALE_PREFIX + key)

    def clear_prefix(self, prefix: str):
        self._inner.clear_prefix(prefix)
        self._inner.clear_prefix(self.STALE_PREFIX + prefix)


cache = _StaleFallback(_create_cache())
