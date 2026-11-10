"""统计服务：课程概览、知识点掌握度、班级错题分布。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Answer,
    Attempt,
    CourseMember,
    Document,
    DocumentChunk,
    Job,
    KnowledgePoint,
    Paper,
    Question,
    User,
)
from app.schemas.attempt import KPMastery
from app.services.access import require_course
from app.services.attempt_service import build_report


async def overview(session: AsyncSession, course_id: int, user: User) -> dict[str, Any]:
    await require_course(session, course_id, user, "member")

    async def count(model: type, *where: Any) -> int:
        stmt = select(func.count()).select_from(model)
        for cond in where:
            stmt = stmt.where(cond)
        return int(await session.scalar(stmt) or 0)

    since = datetime.now(UTC) - timedelta(days=7)
    active = int(
        await session.scalar(
            select(func.count(func.distinct(Attempt.student_id)))
            .select_from(Attempt)
            .where(Attempt.started_at >= since)
        )
        or 0
    )
    avg = await session.scalar(
        select(func.avg(Attempt.total_score))
        .select_from(Attempt)
        .join(Paper, Paper.id == Attempt.paper_id)
        .where(Paper.course_id == course_id, Attempt.status == "graded")
    )
    jobs = await session.execute(
        select(Job).where(Job.course_id == course_id).order_by(Job.created_at.desc()).limit(5)
    )
    return {
        "documents": await count(Document, Document.course_id == course_id, Document.status != "deleted"),
        "chunks": await count(DocumentChunk, DocumentChunk.course_id == course_id),
        "questions": await count(Question, Question.course_id == course_id),
        "published_questions": await count(
            Question, Question.course_id == course_id, Question.status == "published"
        ),
        "papers": await count(Paper, Paper.course_id == course_id),
        "students": await count(
            CourseMember, CourseMember.course_id == course_id, CourseMember.role == "student"
        ),
        "attempts": await count(
            Attempt, Attempt.paper_id.in_(select(Paper.id).where(Paper.course_id == course_id))
        ),
        "active_students_7d": active,
        "avg_score": round(float(avg or 0), 1),
        "knowledge_points": await count(KnowledgePoint, KnowledgePoint.course_id == course_id),
        "recent_jobs": [
            {
                "task_id": j.task_id,
                "job_type": j.job_type,
                "status": j.status,
                "progress": j.progress,
                "stage": j.stage,
                "created_at": j.created_at,
            }
            for j in jobs.scalars().all()
        ],
    }


async def kp_mastery(session: AsyncSession, attempt_id: int, user: User) -> list[KPMastery]:
    report = await build_report(session, attempt_id, user)
    return report.kp_mastery


async def error_heatmap(session: AsyncSession, course_id: int, user: User) -> list[dict[str, Any]]:
    """班级错题分布：按知识点聚合错误次数（教师端学情看板用）。"""
    await require_course(session, course_id, user, "teacher")
    rows = await session.execute(
        select(Question.kp_ids, Answer.is_correct, Answer.error_tags)
        .join(Answer, Answer.question_id == Question.id)
        .join(Attempt, Attempt.id == Answer.attempt_id)
        .join(Paper, Paper.id == Attempt.paper_id)
        .where(Paper.course_id == course_id, Attempt.status == "graded")
    )
    counter: dict[int, dict[str, Any]] = {}
    for kp_ids, is_correct, tags in rows.all():
        for kp_id in kp_ids or []:
            bucket = counter.setdefault(
                int(kp_id), {"kp_id": int(kp_id), "total": 0, "wrong": 0, "tags": {}}
            )
            bucket["total"] += 1
            if is_correct is False:
                bucket["wrong"] += 1
                for tag in tags or []:
                    bucket["tags"][tag] = bucket["tags"].get(tag, 0) + 1
    if not counter:
        return []
    kp_rows = await session.execute(
        select(KnowledgePoint.id, KnowledgePoint.name).where(
            KnowledgePoint.id.in_(list(counter.keys()))
        )
    )
    names = {int(i): n for i, n in kp_rows.all()}
    out = [
        {
            "kp_id": kp_id,
            "name": names.get(kp_id, f"知识点{kp_id}"),
            "total": bucket["total"],
            "wrong": bucket["wrong"],
            "wrong_rate": round(bucket["wrong"] / bucket["total"], 3) if bucket["total"] else 0,
            "top_tags": sorted(bucket["tags"].items(), key=lambda kv: -kv[1])[:3],
        }
        for kp_id, bucket in counter.items()
    ]
    return sorted(out, key=lambda x: -x["wrong_rate"])
