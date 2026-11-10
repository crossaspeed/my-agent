"""缓存：优先 Redis，不可用时退化为进程内 TTL 字典（保证离线可跑）。"""

from __future__ import annotations

import json
import time
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class _MemoryCache:
    def __init__(self) -> None:
        self._store: dict[str, tuple[float, str]] = {}

    def get(self, key: str) -> str | None:
        item = self._store.get(key)
        if not item:
            return None
        expire_at, value = item
        if expire_at < time.time():
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: str, ttl: int) -> None:
        if len(self._store) > 5000:  # 简单防护，避免进程内无限增长
            now = time.time()
            self._store = {k: v for k, v in self._store.items() if v[0] > now}
        self._store[key] = (time.time() + ttl, value)

    def delete_prefix(self, prefix: str) -> int:
        keys = [k for k in self._store if k.startswith(prefix)]
        for k in keys:
            self._store.pop(k, None)
        return len(keys)


_memory = _MemoryCache()
_redis: Any = None
_redis_checked = False


def _get_redis() -> Any:
    global _redis, _redis_checked
    if _redis_checked:
        return _redis
    _redis_checked = True
    if settings.USE_CELERY:  # 只有启用队列（意味着 Redis 可用）时才尝试连接
        try:
            import redis

            client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True,
                                          socket_connect_timeout=1)
            client.ping()
            _redis = client
            logger.info("cache_backend", backend="redis")
        except Exception as exc:  # pragma: no cover - 环境相关
            logger.warning("redis_unavailable", error=str(exc))
            _redis = None
    return _redis


def get_json(key: str) -> Any | None:
    client = _get_redis()
    raw = client.get(key) if client else _memory.get(key)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def set_json(key: str, value: Any, ttl: int) -> None:
    raw = json.dumps(value, ensure_ascii=False, default=str)
    client = _get_redis()
    if client:
        client.setex(key, ttl, raw)
    else:
        _memory.set(key, raw, ttl)


def delete_prefix(prefix: str) -> int:
    client = _get_redis()
    if client:
        count = 0
        for key in client.scan_iter(match=f"{prefix}*", count=200):
            client.delete(key)
            count += 1
        return count
    return _memory.delete_prefix(prefix)
