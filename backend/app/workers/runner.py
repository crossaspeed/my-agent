"""任务投递：优先 Celery，未启用时用进程内线程池（保证克隆即跑）。"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.workers.registry import get_task, load_all

logger = get_logger(__name__)

_executor: ThreadPoolExecutor | None = None


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(
            max_workers=max(1, settings.JOB_WORKERS), thread_name_prefix="job"
        )
    return _executor


async def run_job(job_type: str, payload: dict[str, Any]) -> None:
    """执行单个任务（Celery task 与本地线程池共用）。"""
    load_all()
    task = get_task(job_type)
    await task(payload)


def run_job_sync(job_type: str, payload: dict[str, Any]) -> None:
    asyncio.run(run_job(job_type, payload))


def submit(job_type: str, task_id: str, payload: dict[str, Any]) -> str:
    """投递任务，返回执行后端标识。"""
    payload = {**payload, "task_id": task_id, "job_type": job_type}
    if settings.USE_CELERY:
        from app.workers.celery_app import celery_app

        celery_app.send_task(f"tasks.{job_type}", kwargs={"payload": payload})
        return "celery"

    def _run() -> None:
        try:
            asyncio.run(run_job(job_type, payload))
        except Exception as exc:  # pragma: no cover - 兜底日志
            logger.exception("job_crashed", job_type=job_type, task_id=task_id, error=str(exc))

    _get_executor().submit(_run)
    return "thread"


def shutdown() -> None:
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=False, cancel_futures=True)
        _executor = None
