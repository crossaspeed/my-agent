"""后台任务的事件循环隔离测试。

背景：Celery（prefork）与线程池都是「一个任务一次 asyncio.run」，每次新建事件循环；
复用 API 进程的全局引擎 / 全局 LLM 客户端会抛
`Future attached to a different loop`。这组用例锁定两类隔离：
1. 任务会话使用 NullPool 的一次性引擎（连接不跨任务存活）；
2. LLM 客户端按事件循环缓存（信号量绑定 loop）。
"""

from __future__ import annotations

import asyncio

from sqlalchemy import text


async def _touch_db() -> str:
    from app.db.base import task_session

    async with task_session() as session:
        pool_name = type(session.bind.pool).__name__  # type: ignore[union-attr]
        value = await session.scalar(text("select 1"))
        assert value == 1
        return pool_name


def test_task_session_uses_nullpool():
    pool_name = asyncio.run(_touch_db())
    # 若有人把任务改回全局 AsyncSessionLocal，这里会变成 AsyncAdaptedQueuePool
    assert pool_name == "NullPool"


def test_task_session_across_multiple_event_loops():
    """连续两次 asyncio.run（模拟同一 Celery 子进程处理两个任务）都应成功。"""
    assert asyncio.run(_touch_db()) == "NullPool"
    assert asyncio.run(_touch_db()) == "NullPool"


def test_llm_client_is_cached_per_event_loop():
    from app.agents.llm import get_llm_client

    async def one() -> object:
        return get_llm_client()

    async def two() -> tuple[object, object]:
        return get_llm_client(), get_llm_client()

    first = asyncio.run(one())
    second = asyncio.run(one())
    assert first is not second, "跨事件循环必须拿到不同客户端，否则信号量会绑定到已关闭的循环"

    a, b = asyncio.run(two())
    assert a is b, "同一事件循环内必须复用同一个客户端"
