"""异步任务记录服务：所有进度必须落库（前端 1.5s 轮询可见）。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFound
from app.db.models import Job


def new_task_id() -> str:
    return uuid.uuid4().hex


async def create(
    session: AsyncSession,
    job_type: str,
    target_id: int | None = None,
    course_id: int | None = None,
    created_by: int | None = None,
    payload: dict[str, Any] | None = None,
    task_id: str | None = None,
) -> Job:
    job = Job(
        task_id=task_id or new_task_id(),
        job_type=job_type,
        target_id=target_id,
        course_id=course_id,
        created_by=created_by,
        payload=payload or {},
        status="pending",
        progress=0,
        stage="排队中",
    )
    session.add(job)
    await session.flush()
    return job


async def get(session: AsyncSession, task_id: str) -> Job:
    row = await session.execute(select(Job).where(Job.task_id == task_id))
    job = row.scalar_one_or_none()
    if job is None:
        raise NotFound("任务不存在")
    return job


async def update(
    session: AsyncSession,
    task_id: str,
    *,
    status: str | None = None,
    progress: int | None = None,
    stage: str | None = None,
    result: dict[str, Any] | None = None,
    error_msg: str | None = None,
) -> None:
    job = await get(session, task_id)
    if status is not None:
        job.status = status
    if progress is not None:
        job.progress = max(0, min(100, int(progress)))
    if stage is not None:
        job.stage = stage
    if result is not None:
        job.result = result
    if error_msg is not None:
        job.error_msg = error_msg
    now = datetime.now(UTC)
    if status == "running" and job.started_at is None:
        job.started_at = now
    if status in ("success", "failed", "canceled"):
        job.finished_at = now
    job.heartbeat_at = now
    session.add(job)
    await session.flush()


async def success(session: AsyncSession, task_id: str, result: dict[str, Any] | None = None) -> None:
    await update(session, task_id, status="success", progress=100, stage="已完成", result=result)


async def fail(session: AsyncSession, task_id: str, error_msg: str) -> None:
    await update(session, task_id, status="failed", error_msg=error_msg[:2000], stage="失败")


async def list_by_course(
    session: AsyncSession, course_id: int, limit: int = 20, job_type: str | None = None
) -> list[Job]:
    stmt = select(Job).where(Job.course_id == course_id).order_by(Job.created_at.desc()).limit(limit)
    if job_type:
        stmt = stmt.where(Job.job_type == job_type)
    rows = await session.execute(stmt)
    return list(rows.scalars().all())


async def find_by_target(
    session: AsyncSession, job_type: str, target_id: int
) -> Job | None:
    rows = await session.execute(
        select(Job)
        .where(Job.job_type == job_type, Job.target_id == target_id)
        .order_by(Job.created_at.desc())
        .limit(1)
    )
    return rows.scalar_one_or_none()


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


async def reconcile_stale_jobs(
    session: AsyncSession, *, pending_seconds: int = 600, running_seconds: int = 1800
) -> int:
    """把长时间无进展的非解析类任务标记失败，避免前端无限轮询。

    解析任务由 document_service.reconcile_stuck_documents 负责重新入队，这里跳过；
    其余任务（出题 / 阅卷 / 重建索引）重投不幂等，直接判失败并提示用户重试更安全。
    """
    rows = await session.execute(
        select(Job).where(
            Job.job_type != "parse_document", Job.status.in_(["pending", "running"])
        )
    )
    now = datetime.now(UTC)
    count = 0
    for job in rows.scalars().all():
        if job.status == "pending":
            started = _aware(job.created_at)
            limit = pending_seconds
        else:
            started = _aware(job.heartbeat_at) or _aware(job.started_at) or _aware(job.created_at)
            limit = running_seconds
        if started is None or (now - started).total_seconds() < limit:
            continue
        await fail(
            session,
            job.task_id,
            "任务长时间无进展（服务可能重启过），请重新发起",
        )
        count += 1
    return count
