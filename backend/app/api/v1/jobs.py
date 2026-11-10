"""任务查询与重试路由。"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.deps import CurrentUser, SessionDep
from app.core.exceptions import BadRequest
from app.schemas.common import ok
from app.services import job_service
from app.workers.runner import submit

router = APIRouter(prefix="/jobs", tags=["任务"])


@router.get("/{task_id}", summary="任务状态（前端 1.5s 轮询）")
async def get_job(task_id: str, user: CurrentUser, session: SessionDep):
    job = await job_service.get(session, task_id)
    return ok(job)


@router.post("/{task_id}:retry", summary="重试失败任务")
async def retry(task_id: str, user: CurrentUser, session: SessionDep):
    job = await job_service.get(session, task_id)
    if job.status not in ("failed", "canceled"):
        raise BadRequest("只有失败的任务可以重试")
    payload = dict(job.payload or {})
    new_job = await job_service.create(
        session,
        job_type=job.job_type,
        target_id=job.target_id,
        course_id=job.course_id,
        created_by=user.id,
        payload=payload,
    )
    await session.commit()
    submit(job.job_type, new_job.task_id, {**payload, "task_id": new_job.task_id})
    return ok({"task_id": new_job.task_id}, message="已重新提交")
