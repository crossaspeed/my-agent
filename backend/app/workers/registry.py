"""任务注册表：job_type → 异步执行函数。

之所以单独一张表：Celery 与进程内线程池两种 runner 共用同一份任务实现，
避免「有 Redis 才能跑」的强依赖。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

TaskFn = Callable[[dict[str, Any]], Awaitable[None]]

REGISTRY: dict[str, TaskFn] = {}


def register(job_type: str) -> Callable[[TaskFn], TaskFn]:
    def _wrap(fn: TaskFn) -> TaskFn:
        REGISTRY[job_type] = fn
        return fn

    return _wrap


def get_task(job_type: str) -> TaskFn:
    if job_type not in REGISTRY:
        raise KeyError(f"未注册的任务类型：{job_type}")
    return REGISTRY[job_type]


def load_all() -> None:
    """导入所有任务模块以完成注册。"""
    from app.workers.tasks import generate, grade, parse, reindex  # noqa: F401
