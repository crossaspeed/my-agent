"""作答服务：开始作答、草稿保存、提交、成绩报告、知识点掌握度。"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequest, Conflict, Forbidden, NotFound
from app.db.models import (
    Answer,
    Attempt,
    KnowledgePoint,
    Paper,
    PaperQuestion,
    Question,
    User,
)
from app.schemas.attempt import (
    AnswerDraftOut,
    AttemptOut,
    AttemptReport,
    GradingStatusOut,
    KPMastery,
    ReportItem,
    SubmitOut,
)
from app.services import job_service
from app.services.access import get_course_role, require_course
from app.workers.runner import submit

VALID_SUBMIT_STATUS = ("in_progress", "submitted", "grading", "graded")


def _value_of(answer: Answer | None) -> Any:
    if answer is None or answer.student_answer is None:
        return None
    if isinstance(answer.student_answer, dict):
        return answer.student_answer.get("value")
    return answer.student_answer


def _flagged_of(answer: Answer | None) -> bool:
    if answer is None or not isinstance(answer.student_answer, dict):
        return False
    return bool(answer.student_answer.get("flagged"))


async def _pairs(session: AsyncSession, paper_id: int) -> list[tuple[PaperQuestion, Question]]:
    rows = await session.execute(
        select(PaperQuestion, Question)
        .join(Question, Question.id == PaperQuestion.question_id)
        .where(PaperQuestion.paper_id == paper_id)
        .order_by(PaperQuestion.seq)
    )
    return [(pq, q) for pq, q in rows.all()]


async def _load_attempt(session: AsyncSession, attempt_id: int) -> Attempt:
    attempt = await session.get(Attempt, attempt_id)
    if attempt is None:
        raise NotFound("作答记录不存在")
    return attempt


async def start_attempt(session: AsyncSession, paper_id: int, user: User) -> AttemptOut:
    paper = await session.get(Paper, paper_id)
    if paper is None:
        raise NotFound("试卷不存在")
    _, role = await require_course(session, paper.course_id, user, "member")
    if role in ("owner", "teacher"):
        pass  # 教师可用于预览
    elif paper.status != "published":
        raise BadRequest("试卷尚未发布")

    existing = await session.execute(
        select(Attempt).where(Attempt.paper_id == paper_id, Attempt.student_id == user.id)
    )
    attempt = existing.scalar_one_or_none()
    if attempt is None:
        pairs = await _pairs(session, paper_id)
        if not pairs:
            raise BadRequest("试卷没有题目")
        attempt = Attempt(
            paper_id=paper_id,
            student_id=user.id,
            status="in_progress",
            max_score=Decimal(str(paper.total_score)),
        )
        session.add(attempt)
        await session.flush()
        for pq, _ in pairs:
            session.add(
                Answer(
                    attempt_id=attempt.id,
                    question_id=pq.question_id,
                    student_answer=None,
                    max_score=pq.score,
                )
            )
        await session.flush()
    return await get_attempt(session, attempt.id, user)


async def get_attempt(session: AsyncSession, attempt_id: int, user: User) -> AttemptOut:
    attempt = await _load_attempt(session, attempt_id)
    _, role = await get_course_role(
        session, (await session.get(Paper, attempt.paper_id)).course_id, user
    )
    if attempt.student_id != user.id and role not in ("owner", "teacher"):
        raise Forbidden("无权查看他人作答")

    pairs = await _pairs(session, attempt.paper_id)
    rows = await session.execute(select(Answer).where(Answer.attempt_id == attempt_id))
    answers = {a.question_id: a for a in rows.scalars().all()}
    paper = await session.get(Paper, attempt.paper_id)

    items = []
    for pq, q in pairs:
        answer = answers.get(q.id)
        items.append(
            AnswerDraftOut(
                question_id=q.id,
                seq=pq.seq,
                type=q.type,
                stem=q.stem,
                options=q.options,
                score=float(pq.score),
                value=_value_of(answer),
                flagged=_flagged_of(answer),
            )
        )
    return AttemptOut.model_validate(attempt).model_copy(
        update={
            "paper_title": paper.title if paper else None,
            "duration_min": paper.duration_min if paper else 60,
            "answers": items,
        }
    )


async def save_answer(
    session: AsyncSession, attempt_id: int, question_id: int, user: User, value: Any, flagged: bool
) -> None:
    attempt = await _load_attempt(session, attempt_id)
    if attempt.student_id != user.id:
        raise Forbidden("无权修改他人作答")
    if attempt.status != "in_progress":
        raise Conflict("试卷已提交，不能修改答案")
    row = await session.execute(
        select(Answer).where(
            Answer.attempt_id == attempt_id, Answer.question_id == question_id
        )
    )
    answer = row.scalar_one_or_none()
    if answer is None:
        raise NotFound("该题目不属于此试卷")
    answer.student_answer = {"value": value, "flagged": flagged}
    session.add(answer)
    await session.flush()


async def submit_attempt(session: AsyncSession, attempt_id: int, user: User) -> SubmitOut:
    attempt = await _load_attempt(session, attempt_id)
    if attempt.student_id != user.id:
        raise Forbidden("无权提交他人作答")
    if attempt.status in ("submitted", "grading"):
        job = await job_service.find_by_target(session, "grade_attempt", attempt_id)
        return SubmitOut(
            attempt_id=attempt_id, status=attempt.status,
            job_id=job.task_id if job else None, message="已提交，正在阅卷",
        )
    if attempt.status == "graded":
        return SubmitOut(attempt_id=attempt_id, status="graded", message="已完成阅卷")

    attempt.status = "submitted"
    attempt.submitted_at = datetime.now(UTC)
    session.add(attempt)
    job = await job_service.create(
        session, "grade_attempt", target_id=attempt_id,
        course_id=(await session.get(Paper, attempt.paper_id)).course_id,
        created_by=user.id, payload={"attempt_id": attempt_id},
    )
    await session.commit()
    submit("grade_attempt", job.task_id, {"attempt_id": attempt_id, "task_id": job.task_id})
    return SubmitOut(attempt_id=attempt_id, status="submitted", job_id=job.task_id)


async def grading_status(session: AsyncSession, attempt_id: int, user: User) -> GradingStatusOut:
    attempt = await _load_attempt(session, attempt_id)
    paper = await session.get(Paper, attempt.paper_id)
    _, role = await get_course_role(session, paper.course_id, user)
    if attempt.student_id != user.id and role not in ("owner", "teacher"):
        raise Forbidden("无权查看")
    total = int(
        await session.scalar(
            select(func.count()).select_from(Answer).where(Answer.attempt_id == attempt_id)
        )
        or 0
    )
    graded = int(
        await session.scalar(
            select(func.count())
            .select_from(Answer)
            .where(Answer.attempt_id == attempt_id, Answer.graded_at.is_not(None))
        )
        or 0
    )
    job = await job_service.find_by_target(session, "grade_attempt", attempt_id)
    return GradingStatusOut(
        attempt_id=attempt_id,
        status=attempt.status,
        graded=graded,
        total=total,
        progress=int(graded / total * 100) if total else 0,
        job_id=job.task_id if job else None,
    )


async def build_report(session: AsyncSession, attempt_id: int, user: User) -> AttemptReport:
    attempt = await _load_attempt(session, attempt_id)
    paper = await session.get(Paper, attempt.paper_id)
    _, role = await get_course_role(session, paper.course_id, user)
    if attempt.student_id != user.id and role not in ("owner", "teacher"):
        raise Forbidden("无权查看该报告")
    if attempt.status in ("in_progress", "submitted", "grading"):
        # 未完成阅卷时也返回当前进度，前端据 status 展示「阅卷中」
        pass

    pairs = await _pairs(session, attempt.paper_id)
    rows = await session.execute(select(Answer).where(Answer.attempt_id == attempt_id))
    answers = {a.question_id: a for a in rows.scalars().all()}

    kp_ids: set[int] = set()
    for _, q in pairs:
        kp_ids.update(q.kp_ids or [])
    kp_names: dict[int, str] = {}
    if kp_ids:
        kp_rows = await session.execute(
            select(KnowledgePoint.id, KnowledgePoint.name).where(KnowledgePoint.id.in_(kp_ids))
        )
        kp_names = {int(i): n for i, n in kp_rows.all()}
    mastery: dict[int, KPMastery] = {
        kp_id: KPMastery(kp_id=kp_id, name=kp_names.get(kp_id, f"知识点{kp_id}"))
        for kp_id in kp_ids
    }

    items: list[ReportItem] = []
    total_score = 0.0
    max_score = 0.0
    tag_stats: dict[str, int] = {}
    for pq, q in pairs:
        answer = answers.get(q.id)
        score = float(answer.score or 0) if answer else 0.0
        item_max = float(pq.score)
        total_score += score
        max_score += item_max
        item = ReportItem(
            seq=pq.seq,
            question_id=q.id,
            type=q.type,
            stem=q.stem,
            options=q.options,
            student_answer=_value_of(answer),
            correct_answer=q.answer,
            is_correct=answer.is_correct if answer else None,
            score=round(score, 2),
            max_score=round(item_max, 2),
            rubric_detail=answer.rubric_detail or [] if answer else [],
            feedback=answer.feedback if answer else None,
            error_tags=(answer.error_tags or []) if answer else [],
            needs_human=bool(answer.needs_human) if answer else False,
            graded_by=answer.graded_by if answer else None,
            source_refs=q.source_refs or [],
        )
        items.append(item)
        for tag in item.error_tags:
            tag_stats[tag] = tag_stats.get(tag, 0) + 1
        for kp_id in q.kp_ids or []:
            if kp_id in mastery:
                mastery[kp_id].total_score += item_max
                mastery[kp_id].earned_score += score
                mastery[kp_id].question_count += 1
                if item.is_correct is False:
                    mastery[kp_id].wrong_count += 1

    for kp in mastery.values():
        kp.rate = round(kp.earned_score / kp.total_score, 3) if kp.total_score else 0.0
        kp.earned_score = round(kp.earned_score, 2)
        kp.total_score = round(kp.total_score, 2)

    wrong = [i for i in items if i.is_correct is False or i.score < i.max_score]
    duration = None
    if attempt.submitted_at and attempt.started_at:
        start = attempt.started_at if attempt.started_at.tzinfo else attempt.started_at.replace(tzinfo=UTC)
        end = attempt.submitted_at if attempt.submitted_at.tzinfo else attempt.submitted_at.replace(tzinfo=UTC)
        duration = int((end - start).total_seconds())

    return AttemptReport(
        attempt_id=attempt.id,
        paper_id=attempt.paper_id,
        course_id=paper.course_id,
        paper_title=paper.title,
        student_id=attempt.student_id,
        status=attempt.status,
        total_score=round(total_score, 2),
        max_score=round(max_score, 2),
        score_rate=round(total_score / max_score, 3) if max_score else 0.0,
        duration_seconds=duration,
        items=items,
        kp_mastery=sorted(mastery.values(), key=lambda k: k.kp_id),
        wrong_items=wrong,
        error_tag_stats=tag_stats,
        needs_human_count=sum(1 for i in items if i.needs_human),
    )


async def list_my_attempts(session: AsyncSession, user: User) -> list[dict[str, Any]]:
    rows = await session.execute(
        select(Attempt, Paper.title, Paper.total_score)
        .join(Paper, Paper.id == Attempt.paper_id)
        .where(Attempt.student_id == user.id)
        .order_by(Attempt.started_at.desc())
    )
    return [
        {
            "attempt_id": a.id,
            "paper_id": a.paper_id,
            "paper_title": title,
            "status": a.status,
            "total_score": float(a.total_score) if a.total_score is not None else None,
            "max_score": float(a.max_score or total or 0),
            "started_at": a.started_at,
            "submitted_at": a.submitted_at,
        }
        for a, title, total in rows.all()
    ]
