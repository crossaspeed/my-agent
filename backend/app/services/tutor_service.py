"""导学服务：会话管理、开场讲解、SSE 流式追问、练习推荐。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.orchestrator import orchestrator
from app.core.config import settings
from app.core.exceptions import BadRequest, Forbidden, NotFound
from app.core.logging import get_logger
from app.core.ratelimit import check_rate_limit
from app.db.base import AsyncSessionLocal
from app.db.models import (
    Answer,
    Attempt,
    Course,
    KnowledgePoint,
    Paper,
    Question,
    TutorMessage,
    TutorSession,
    User,
)
from app.schemas.tutor import TutorSendRequest, TutorSessionOut
from app.services.access import require_course

logger = get_logger(__name__)

HISTORY_WINDOW = 10


def format_sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


async def _context_of_answer(
    session: AsyncSession, answer_id: int, user: User
) -> dict[str, Any]:
    answer = await session.get(Answer, answer_id)
    if answer is None:
        raise NotFound("作答记录不存在")
    attempt = await session.get(Attempt, answer.attempt_id)
    if attempt is None or attempt.student_id != user.id:
        raise Forbidden("无权访问该作答")
    paper = await session.get(Paper, attempt.paper_id)
    question = await session.get(Question, answer.question_id)
    if paper is None or question is None:
        raise NotFound("题目或试卷不存在")
    await require_course(session, paper.course_id, user, "member")
    return {
        "course_id": paper.course_id,
        "question": question,
        "answer": answer,
        "grading": {
            "score": float(answer.score or 0),
            "max_score": float(answer.max_score or 0),
            "rubric_detail": answer.rubric_detail or [],
            "feedback": answer.feedback or "",
            "error_tags": answer.error_tags or [],
        },
    }


async def _kp_maps(session: AsyncSession, course_id: int) -> tuple[dict[int, str], dict[str, int]]:
    rows = await session.execute(
        select(KnowledgePoint.id, KnowledgePoint.name).where(KnowledgePoint.course_id == course_id)
    )
    by_id = {int(i): n for i, n in rows.all()}
    return by_id, {v: k for k, v in by_id.items()}


def _question_dict(question: Question) -> dict[str, Any]:
    return {
        "id": question.id,
        "type": question.type,
        "stem": question.stem,
        "options": question.options,
        "answer": question.answer,
        "rubric": question.rubric or [],
        "explanation": question.explanation,
        "kp_ids": question.kp_ids or [],
    }


async def create_session(
    session: AsyncSession, user: User, answer_id: int | None, course_id: int | None,
    question_id: int | None,
) -> dict[str, Any]:
    check_rate_limit(f"tutor:{user.id}", limit=settings.MAX_TUTOR_TURNS_PER_HOUR, window_seconds=3600)

    if answer_id:
        ctx = await _context_of_answer(session, answer_id, user)
        question = ctx["question"]
        course_id = ctx["course_id"]
        answer_payload = {"value": (ctx["answer"].student_answer or {}).get("value")
                          if isinstance(ctx["answer"].student_answer, dict)
                          else ctx["answer"].student_answer}
        grading = ctx["grading"]
    else:
        if not course_id or not question_id:
            raise BadRequest("请提供 answer_id，或同时提供 course_id 与 question_id")
        await require_course(session, course_id, user, "member")
        question = await session.get(Question, question_id)
        if question is None or question.course_id != course_id:
            raise NotFound("题目不存在")
        answer_payload = {"value": None}
        grading = {"error_tags": [], "rubric_detail": [], "feedback": ""}

    course = await session.get(Course, course_id)
    title = f"错题讲解：{question.stem[:24]}"
    tutor_session = TutorSession(
        student_id=user.id,
        course_id=course_id,
        answer_id=answer_id,
        question_id=question.id,
        title=title,
        last_active_at=datetime.now(UTC),
    )
    session.add(tutor_session)
    await session.commit()  # 先释放写事务，避免长耗时 LLM 调用期间锁库

    kp_by_id, kp_names = await _kp_maps(session, course_id)
    state = await orchestrator.tutor_answer(
        session=session,
        course_id=course_id,
        course_name=course.name if course else "",
        question=_question_dict(question),
        answer=answer_payload,
        grading=grading,
        history=[],
        user_query=None,
        kp_name_by_id=kp_by_id,
        student_id=user.id,
        session_id=tutor_session.id,
    )
    content = state.get("final_answer") or state.get("explanation") or ""
    refs = state.get("refs") or []
    message = TutorMessage(
        session_id=tutor_session.id,
        role="assistant",
        content=content,
        refs=refs,
        meta={"tokens": state.get("tokens", 0), "diagnosis": state.get("diagnosis", "")},
    )
    session.add(message)
    await session.commit()

    return {
        "session_id": tutor_session.id,
        "message": {
            "id": message.id,
            "session_id": tutor_session.id,
            "role": "assistant",
            "content": content,
            "refs": refs,
            "meta": message.meta,
            "created_at": message.created_at,
        },
        "refs": refs,
        "practice": state.get("practice") or [],
        "diagnosis": state.get("diagnosis") or "",
    }


async def list_sessions(session: AsyncSession, user: User) -> list[TutorSessionOut]:
    rows = await session.execute(
        select(TutorSession)
        .where(TutorSession.student_id == user.id)
        .order_by(TutorSession.id.desc())
        .limit(50)
    )
    sessions = list(rows.scalars().all())
    out: list[TutorSessionOut] = []
    for item in sessions:
        count = int(
            await session.scalar(
                select(func.count()).select_from(TutorMessage).where(
                    TutorMessage.session_id == item.id
                )
            )
            or 0
        )
        last = await session.execute(
            select(TutorMessage.content)
            .where(TutorMessage.session_id == item.id, TutorMessage.role == "assistant")
            .order_by(TutorMessage.id.desc())
            .limit(1)
        )
        out.append(
            TutorSessionOut.model_validate(item).model_copy(
                update={"message_count": count, "last_message": (last.scalar_one_or_none() or "")[:80]}
            )
        )
    return out


async def get_session(session: AsyncSession, session_id: int, user: User) -> dict[str, Any]:
    tutor_session = await session.get(TutorSession, session_id)
    if tutor_session is None:
        raise NotFound("会话不存在")
    if tutor_session.student_id != user.id:
        raise Forbidden("无权访问该会话")
    rows = await session.execute(
        select(TutorMessage)
        .where(TutorMessage.session_id == session_id)
        .order_by(TutorMessage.id)
        .limit(200)
    )
    messages = [
        {
            "id": m.id,
            "session_id": m.session_id,
            "role": m.role,
            "content": m.content,
            "refs": m.refs or [],
            "meta": m.meta,
            "created_at": m.created_at,
        }
        for m in rows.scalars().all()
    ]
    return {
        "id": tutor_session.id,
        "student_id": tutor_session.student_id,
        "course_id": tutor_session.course_id,
        "answer_id": tutor_session.answer_id,
        "question_id": tutor_session.question_id,
        "title": tutor_session.title,
        "summary": tutor_session.summary,
        "created_at": tutor_session.created_at,
        "last_active_at": tutor_session.last_active_at,
        "message_count": len(messages),
        "messages": messages,
    }


async def delete_session(session: AsyncSession, session_id: int, user: User) -> None:
    tutor_session = await session.get(TutorSession, session_id)
    if tutor_session is None:
        raise NotFound("会话不存在")
    if tutor_session.student_id != user.id:
        raise Forbidden("无权删除该会话")
    await session.execute(
        TutorMessage.__table__.delete().where(TutorMessage.session_id == session_id)
    )
    await session.delete(tutor_session)


async def _build_stream_state(
    db: AsyncSession, session_id: int, user_id: int, user_query: str
) -> dict[str, Any]:
    tutor_session = await db.get(TutorSession, session_id)
    if tutor_session is None:
        raise NotFound("会话不存在")
    if tutor_session.student_id != user_id:
        raise Forbidden("无权访问该会话")
    question = await db.get(Question, tutor_session.question_id) if tutor_session.question_id else None
    answer = await db.get(Answer, tutor_session.answer_id) if tutor_session.answer_id else None
    paper = await db.get(Paper, (await db.get(Attempt, answer.attempt_id)).paper_id) if answer else None
    course = await db.get(Course, tutor_session.course_id)
    rows = await db.execute(
        select(TutorMessage)
        .where(TutorMessage.session_id == session_id)
        .order_by(TutorMessage.id.desc())
        .limit(HISTORY_WINDOW)
    )
    history = [
        {"role": m.role, "content": m.content}
        for m in reversed(rows.scalars().all())
    ]
    kp_by_id, _ = await _kp_maps(db, tutor_session.course_id)
    assert paper is not None or answer is None
    return {
        "session": db,
        "session_id": session_id,
        "course_id": tutor_session.course_id,
        "course_name": course.name if course else "",
        "question": _question_dict(question) if question else {},
        "answer": {
            "value": (answer.student_answer or {}).get("value")
            if answer and isinstance(answer.student_answer, dict)
            else None
        },
        "grading": {
            "score": float(answer.score or 0) if answer else 0,
            "max_score": float(answer.max_score or 0) if answer else 0,
            "rubric_detail": (answer.rubric_detail or []) if answer else [],
            "feedback": (answer.feedback or "") if answer else "",
            "error_tags": (answer.error_tags or []) if answer else [],
        },
        "history": history,
        "user_query": user_query,
        "kp_name_by_id": kp_by_id,
        "student_id": user_id,
    }


async def stream_message(
    session_id: int, user: User, req: TutorSendRequest
) -> AsyncIterator[str]:
    """SSE 生成器：meta → token* → refs → done / error。"""
    check_rate_limit(f"tutor:{user.id}", limit=settings.MAX_TUTOR_TURNS_PER_HOUR, window_seconds=3600)
    async with AsyncSessionLocal() as db:
        try:
            kwargs = await _build_stream_state(db, session_id, user.id, req.content)
        except (NotFound, Forbidden) as exc:
            yield format_sse("error", {"code": exc.code, "message": exc.message})
            return

        user_msg = TutorMessage(session_id=session_id, role="user", content=req.content)
        db.add(user_msg)
        await db.commit()
        user_message_id = user_msg.id

        yield format_sse("meta", {"session_id": session_id, "message_id": user_message_id})

        parts: list[str] = []
        refs: list[dict[str, Any]] = []
        practice: list[dict[str, Any]] = []
        try:
            async for event in orchestrator.tutor_stream(**kwargs):
                if event["event"] == "token":
                    parts.append(event["data"]["delta"])
                    yield format_sse("token", event["data"])
                elif event["event"] == "refs":
                    refs = event["data"].get("refs") or []
                    practice = event["data"].get("practice") or []
                    yield format_sse(
                        "refs",
                        {"refs": refs, "practice": practice,
                         "diagnosis": event["data"].get("diagnosis", "")},
                    )
                elif event["event"] == "done":
                    content = event["data"].get("content") or "".join(parts)
                    assistant = TutorMessage(
                        session_id=session_id,
                        role="assistant",
                        content=content,
                        refs=refs,
                        meta={"practice": practice},
                    )
                    db.add(assistant)
                    await db.flush()
                    tutor_session = await db.get(TutorSession, session_id)
                    if tutor_session is not None:
                        tutor_session.last_active_at = datetime.now(UTC)
                        db.add(tutor_session)
                    await db.commit()
                    yield format_sse(
                        "done",
                        {"message_id": assistant.id, "content": content, "refs": refs,
                         "practice": practice, "tokens": 0},
                    )
        except Exception as exc:  # 保留已收到内容，前端可重试
            logger.warning("tutor_stream_error", session_id=session_id, error=str(exc))
            yield format_sse(
                "error",
                {"code": 5001, "message": f"模型输出中断：{exc}", "partial": "".join(parts)},
            )
