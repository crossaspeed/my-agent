"""阅卷服务：整卷异步阅卷（题目级并发，单题失败不影响整卷）。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.orchestrator import orchestrator
from app.core.logging import get_logger
from app.db.base import task_session
from app.db.models import Answer, Attempt, Paper, PaperQuestion, Question
from app.services import job_service
from app.workers.registry import register

logger = get_logger(__name__)

MAX_GRADE_CONCURRENCY = 4


def _value_of(payload: Any) -> Any:
    if isinstance(payload, dict):
        return payload.get("value")
    return payload


async def _grade_one(
    course_id: int,
    course_name: str,
    question: dict[str, Any],
    value: Any,
    max_score: float,
) -> dict[str, Any]:
    async with task_session() as session:
        try:
            return await orchestrator.grade_answer(
                session=session,
                course_id=course_id,
                course_name=course_name,
                question=question,
                student_answer=value,
                max_score=max_score,
                trace_id=f"grade-{question.get('id')}",
            )
        except Exception as exc:  # 单题失败不阻断整卷
            logger.warning("grade_one_failed", question_id=question.get("id"), error=str(exc))
            return {
                "score": 0.0,
                "is_correct": None,
                "rubric_detail": [],
                "feedback": "阅卷服务暂时不可用，该题待人工复核",
                "error_tags": [],
                "graded_by": "agent",
                "confidence": 0.0,
                "needs_human": True,
                "warnings": [str(exc)],
            }


async def grade_attempt(session: AsyncSession, attempt_id: int, task_id: str | None = None) -> dict[str, Any]:
    attempt = await session.get(Attempt, attempt_id)
    if attempt is None:
        raise ValueError("作答记录不存在")
    paper = await session.get(Paper, attempt.paper_id)
    if paper is None:
        raise ValueError("试卷不存在")
    course_name = ""
    from app.db.models import Course

    course = await session.get(Course, paper.course_id)
    if course is not None:
        course_name = course.name

    attempt.status = "grading"
    session.add(attempt)
    if task_id:
        await job_service.update(session, task_id, status="running", progress=10, stage="抽取要点…")
    await session.commit()

    rows = await session.execute(
        select(PaperQuestion, Question, Answer)
        .join(Question, Question.id == PaperQuestion.question_id)
        .join(Answer, (Answer.question_id == PaperQuestion.question_id)
              & (Answer.attempt_id == attempt_id))
        .where(PaperQuestion.paper_id == paper.id)
        .order_by(PaperQuestion.seq)
    )
    triples = [(pq, q, a) for pq, q, a in rows.all()]

    semaphore = asyncio.Semaphore(MAX_GRADE_CONCURRENCY)
    total = len(triples)
    done = 0
    results: dict[int, dict[str, Any]] = {}

    async def _worker(pq: PaperQuestion, question: Question, answer: Answer) -> tuple[int, dict[str, Any]]:
        async with semaphore:
            question_dict = {
                "id": question.id,
                "type": question.type,
                "stem": question.stem,
                "options": question.options,
                "answer": question.answer,
                "rubric": question.rubric or [],
                "explanation": question.explanation,
                "difficulty": question.difficulty,
                "kp_ids": question.kp_ids or [],
            }
            result = await _grade_one(
                paper.course_id,
                course_name,
                question_dict,
                _value_of(answer.student_answer),
                float(pq.score),
            )
            return question.id, result

    tasks = [asyncio.create_task(_worker(pq, q, a)) for pq, q, a in triples]
    for done, future in enumerate(asyncio.as_completed(tasks), start=1):
        qid, result = await future
        results[qid] = result
        if task_id:
            await job_service.update(
                session, task_id, progress=10 + int(80 * done / max(total, 1)), stage="逐题评分…"
            )
            await session.commit()

    total_score = 0.0
    max_score = 0.0
    needs_human = 0
    for pq, question, answer in triples:
        result = results.get(question.id) or {}
        answer.score = Decimal(str(round(float(result.get("score", 0)), 2)))
        answer.is_correct = result.get("is_correct")
        answer.rubric_detail = result.get("rubric_detail") or []
        answer.feedback = result.get("feedback") or ""
        answer.error_tags = result.get("error_tags") or []
        answer.graded_by = result.get("graded_by") or "agent"
        answer.confidence = Decimal(str(round(float(result.get("confidence", 0)), 2)))
        answer.needs_human = bool(result.get("needs_human"))
        answer.graded_at = datetime.now(UTC)
        total_score += float(answer.score or 0)
        max_score += float(pq.score)
        if answer.needs_human:
            needs_human += 1
        session.add(answer)

    attempt.total_score = Decimal(str(round(total_score, 2)))
    attempt.max_score = Decimal(str(round(max_score, 2)))
    attempt.status = "graded"
    attempt.graded_at = datetime.now(UTC)
    session.add(attempt)

    summary = {
        "attempt_id": attempt_id,
        "total_score": round(total_score, 2),
        "max_score": round(max_score, 2),
        "needs_human": needs_human,
        "questions": total,
    }
    if task_id:
        await job_service.success(session, task_id, result=summary)
    await session.commit()
    logger.info("attempt_graded", **summary)
    return summary


@register("grade_attempt")
async def grade_attempt_task(payload: dict[str, Any]) -> None:
    task_id = payload["task_id"]
    attempt_id = int(payload["attempt_id"])
    async with task_session() as session:
        try:
            await grade_attempt(session, attempt_id, task_id)
        except Exception as exc:
            logger.exception("grade_attempt_failed", attempt_id=attempt_id, error=str(exc))
            await job_service.fail(session, task_id, str(exc))
            attempt = await session.get(Attempt, attempt_id)
            if attempt is not None and attempt.status == "grading":
                attempt.status = "submitted"  # 允许「继续阅卷」
                session.add(attempt)
            await session.commit()
