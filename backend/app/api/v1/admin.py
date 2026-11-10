"""管理路由：重建索引、LLM 调用统计、依赖健康检查。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter
from sqlalchemy import func, select

from app.core.config import settings
from app.core.deps import CurrentUser, SessionDep
from app.db.models import LLMCall
from app.rag.embedder import get_embedder
from app.rag.vector_store import get_vector_store
from app.schemas.common import ok
from app.schemas.job import ReindexRequest
from app.services import job_service
from app.workers.runner import submit

router = APIRouter(prefix="/admin", tags=["管理"])


@router.get("/health", summary="依赖健康检查（pg / 向量库 / LLM）")
async def health(session: SessionDep):
    deps: dict[str, object] = {}
    try:
        await session.execute(select(1))
        deps["database"] = "ok"
    except Exception as exc:  # pragma: no cover
        deps["database"] = f"error: {exc}"
    try:
        store = get_vector_store()
        deps["vector"] = {"backend": store.backend, "healthy": await store.health(),
                          "count": await store.count()}
    except Exception as exc:  # pragma: no cover
        deps["vector"] = f"error: {exc}"
    try:
        deps["embedding"] = {"provider": get_embedder().provider,
                             "dim": get_embedder().dim,
                             "healthy": await get_embedder().health()}
    except Exception as exc:  # pragma: no cover
        deps["embedding"] = f"error: {exc}"
    from app.agents.llm import get_llm_client

    client = get_llm_client()
    deps["llm"] = {"provider": settings.LLM_PROVIDER, "model": client.model,
                   "healthy": await client.health()}
    return ok({"status": "ok", "app_env": settings.APP_ENV, "dependencies": deps})


@router.post("/reindex", summary="重建向量索引（换 embedding 模型后必须执行）")
async def reindex(
    req: ReindexRequest,
    user: CurrentUser,
    session: SessionDep,
):
    if user.role not in ("admin", "teacher"):
        from app.core.exceptions import Forbidden

        raise Forbidden("仅管理员/教师可重建索引")
    job = await job_service.create(
        session, "reindex_course", course_id=req.course_id, created_by=user.id,
        payload={"course_id": req.course_id},
    )
    await session.commit()
    submit("reindex_course", job.task_id, {"course_id": req.course_id, "task_id": job.task_id})
    return ok({"task_id": job.task_id})


@router.get("/llm-calls", summary="LLM 调用统计（论文性能章节数据）")
async def llm_calls(user: CurrentUser, session: SessionDep, days: int = 7):
    since = datetime.now(UTC) - timedelta(days=days)
    total = int(
        await session.scalar(select(func.count()).select_from(LLMCall).where(LLMCall.created_at >= since))
        or 0
    )
    success = int(
        await session.scalar(
            select(func.count())
            .select_from(LLMCall)
            .where(LLMCall.created_at >= since, LLMCall.success.is_(True))
        )
        or 0
    )
    avg_latency = float(
        await session.scalar(
            select(func.avg(LLMCall.latency_ms)).where(LLMCall.created_at >= since)
        )
        or 0
    )
    tokens = int(
        await session.scalar(
            select(func.coalesce(func.sum(LLMCall.total_tokens), 0)).where(
                LLMCall.created_at >= since
            )
        )
        or 0
    )
    by_scene_rows = await session.execute(
        select(
            LLMCall.scene,
            func.count(),
            func.avg(LLMCall.latency_ms),
            func.coalesce(func.sum(LLMCall.total_tokens), 0),
        )
        .where(LLMCall.created_at >= since)
        .group_by(LLMCall.scene)
    )
    return ok(
        {
            "total_calls": total,
            "success_rate": round(success / total, 3) if total else 0,
            "avg_latency_ms": round(avg_latency, 1),
            "total_tokens": tokens,
            "by_scene": [
                {
                    "scene": scene,
                    "calls": calls,
                    "avg_latency_ms": round(float(lat or 0), 1),
                    "tokens": int(tokens),
                }
                for scene, calls, lat, tokens in by_scene_rows.all()
            ],
            "by_day": [],
        }
    )
