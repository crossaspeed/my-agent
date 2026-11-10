"""限流：Redis 滑动窗口，或进程内滑动窗口（降级）。"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from app.core.cache import _get_redis
from app.core.exceptions import RateLimited

_local: dict[str, deque[float]] = defaultdict(deque)


def check_rate_limit(key: str, limit: int, window_seconds: int = 3600) -> int:
    """返回窗口内剩余次数；超限抛 RateLimited。"""
    client = _get_redis()
    if client is not None:  # pragma: no cover - 依赖外部服务
        bucket = f"rl:{key}:{int(time.time()) // window_seconds}"
        try:
            count = client.incr(bucket)
            if count == 1:
                client.expire(bucket, window_seconds)
            if count > limit:
                raise RateLimited(f"本小时最多 {limit} 次，请稍后再试")
            return limit - count
        except RateLimited:
            raise
        except Exception:
            pass  # Redis 故障时降级到本地限流

    now = time.time()
    q = _local[key]
    while q and q[0] < now - window_seconds:
        q.popleft()
    if len(q) >= limit:
        raise RateLimited(f"本小时最多 {limit} 次，请稍后再试")
    q.append(now)
    return limit - len(q)


def reset_rate_limit(key: str | None = None) -> None:
    if key is None:
        _local.clear()
    else:
        _local.pop(key, None)
