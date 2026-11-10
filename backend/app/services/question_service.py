"""题目服务：出题任务投递、题库查询、审核状态机、重复题检测。"""

from __future__ import annotations

import uuid
from typing import Any

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.orchestrator import build_kp_specs, orchestrator
from app.core.config import settings
from app.core.exceptions import BadRequest, Forbidden, KnowledgeNotCovered, NotFound
from app.core.logging import get_logger
from app.core.ratelimit import check_rate_limit
from app.db.base import AsyncSessionLocal
from app.db.models import Answer, Attempt, Document, DocumentChunk, Question, User
from app.rag.embedder import get_embedder
from app.schemas.question import GenerateRequest, QuestionOut, QuestionUpdate
from app.services import job_service
from app.services.access import require_course
from app.workers.registry import register
from app.workers.runner import submit

logger = get_logger(__name__)

VALID_STATUS = {"draft", "published", "rejected", "archived"}
DEFAULT_SCORE = 5.0


async def generate_questions(
    session: AsyncSession, course_id: int, user: User, req: GenerateRequest
) -> dict[str, Any]:
    course, _ = await require_course(session, course_id, user, "teacher")
    check_rate_limit(f"gen:{user.id}", limit=10, window_seconds=3600)

    total = sum(req.types.values())
    if total <= 0:
        raise BadRequest("请至少选择一种题型并设置数量")
    if total > settings.MAX_GENERATE_COUNT:
        raise BadRequest(f"单次最多生成 {settings.MAX_GENERATE_COUNT} 道题")

    kps = await _load_kps(session, course_id, req.kp_ids)
    if not kps:
        raise BadRequest("课程尚未创建知识点，请先创建或自动抽取知识点")

    chunks_count = int(
        await session.scalar(
            select(func.count())
            .select_from(DocumentChunk)
            .where(DocumentChunk.course_id == course_id)
        )
        or 0
    )
    if chunks_count == 0:
        raise KnowledgeNotCovered("知识库为空，请先上传并解析课件")

    course_settings = course.settings or {}
    score_per_question = float(course_settings.get("score_per_question") or DEFAULT_SCORE)
    doc_ids = req.source_doc_ids
    if doc_ids:
        valid_docs = await session.execute(
            select(Document.id).where(
                Document.id.in_(doc_ids), Document.course_id == course_id, Document.status == "ready"
            )
        )
        doc_ids = [int(r[0]) for r in valid_docs.all()] or None

    specs = build_kp_specs(
        kp_ids=[kp["id"] for kp in kps],
        kp_names={kp["id"]: kp["name"] for kp in kps},
        types=req.types,
        difficulty=req.difficulty,
        score_per_question=score_per_question,
    )
    payload = {
        "course_id": course_id,
        "user_id": user.id,
        "course_name": course.name,
        "kp_specs": specs,
        "requirements": req.requirements,
        "doc_ids": doc_ids,
        "auto_publish": req.auto_publish,
        "score_per_question": score_per_question,
        "trace_id": uuid.uuid4().hex,
    }
    job = await job_service.create(
        session, "generate_questions", course_id=course_id, created_by=user.id, payload=payload
    )
    await session.commit()
    submit("generate_questions", job.task_id, {**payload, "task_id": job.task_id})
    return {"job_id": job.task_id, "estimated_seconds": max(20, total * 6)}


async def _load_kps(session: AsyncSession, course_id: int, kp_ids: list[int]) -> list[dict[str, Any]]:
    from app.db.models import KnowledgePoint

    stmt = select(KnowledgePoint).where(KnowledgePoint.course_id == course_id)
    if kp_ids:
        stmt = stmt.where(KnowledgePoint.id.in_(kp_ids))
    rows = (await session.execute(stmt.order_by(KnowledgePoint.id))).scalars().all()
    return [{"id": kp.id, "name": kp.name, "importance": kp.importance} for kp in rows]


def question_to_out(question: Question, reveal_answer: bool = True) -> QuestionOut:
    data = QuestionOut.model_validate(question)
    if reveal_answer:
        return data
    return data.model_copy(
        update={"answer": None, "rubric": [], "explanation": None,
                "quality": None, "source_refs": []}
    )


async def list_questions(
    session: AsyncSession,
    course_id: int,
    user: User,
    page: int = 1,
    size: int = 20,
    status: str | None = None,
    qtype: str | None = None,
    kp_id: int | None = None,
    keyword: str | None = None,
) -> dict[str, Any]:
    await require_course(session, course_id, user, "member")
    stmt = select(Question).where(Question.course_id == course_id)
    if status:
        stmt = stmt.where(Question.status == status)
    if qtype:
        stmt = stmt.where(Question.type == qtype)
    if keyword:
        stmt = stmt.where(Question.stem.contains(keyword))
    rows = (await session.execute(stmt.order_by(Question.id.desc()))).scalars().all()
    if kp_id:
        rows = [r for r in rows if kp_id in (r.kp_ids or [])]
    total = len(rows)
    start = (page - 1) * size
    page_rows = rows[start : start + size]
    return {
        "items": [question_to_out(r, reveal_answer=True).model_dump() for r in page_rows],
        "total": total,
        "page": page,
        "size": size,
    }


async def get_question(session: AsyncSession, question_id: int, user: User) -> QuestionOut:
    question = await session.get(Question, question_id)
    if question is None:
        raise NotFound("题目不存在")
    _, role = await require_course(session, question.course_id, user, "member")
    if role in ("owner", "teacher"):
        return question_to_out(question, True)
    # 学生：仅在提交过该题后才能看到答案
    submitted = await session.scalar(
        select(func.count())
        .select_from(Answer)
        .join(Attempt, Attempt.id == Answer.attempt_id)
        .where(
            Answer.question_id == question_id,
            Attempt.student_id == user.id,
            Attempt.status.in_(["submitted", "grading", "graded"]),
        )
    )
    return question_to_out(question, bool(submitted))


async def update_question(
    session: AsyncSession, question_id: int, user: User, req: QuestionUpdate
) -> QuestionOut:
    question = await session.get(Question, question_id)
    if question is None:
        raise NotFound("题目不存在")
    await require_course(session, question.course_id, user, "teacher")
    for field in ("stem", "options", "answer", "rubric", "explanation", "difficulty", "kp_ids"):
        value = getattr(req, field)
        if value is not None:
            setattr(question, field, value)
    question.reviewed_by = user.id
    if question.status == "rejected":
        question.status = "draft"
    session.add(question)
    await session.flush()
    return question_to_out(question, True)


async def review_question(
    session: AsyncSession, question_id: int, user: User, action: str, note: str | None
) -> QuestionOut:
    question = await session.get(Question, question_id)
    if question is None:
        raise NotFound("题目不存在")
    await require_course(session, question.course_id, user, "teacher")
    if question.status == "archived":
        raise BadRequest("已归档题目不能审核")
    question.status = "published" if action == "approve" else "rejected"
    question.reviewed_by = user.id
    question.review_note = note
    session.add(question)
    await session.flush()
    return question_to_out(question, True)


async def batch_review(
    session: AsyncSession, user: User, ids: list[int], action: str, note: str | None
) -> dict[str, int]:
    updated = 0
    for qid in ids:
        question = await session.get(Question, qid)
        if question is None:
            continue
        _, role = await require_course(session, question.course_id, user, "teacher")
        if role not in ("owner", "teacher"):
            raise Forbidden("无权审核该题目")
        question.status = "published" if action == "approve" else "rejected"
        question.reviewed_by = user.id
        question.review_note = note
        session.add(question)
        updated += 1
    await session.flush()
    return {"updated": updated}


async def archive_question(session: AsyncSession, question_id: int, user: User) -> None:
    question = await session.get(Question, question_id)
    if question is None:
        raise NotFound("题目不存在")
    await require_course(session, question.course_id, user, "teacher")
    question.status = "archived"
    session.add(question)


async def review_queue(session: AsyncSession, course_id: int, user: User) -> dict[str, Any]:
    await require_course(session, course_id, user, "teacher")
    rows = await session.execute(
        select(Question)
        .where(Question.course_id == course_id, Question.status.in_(["draft", "rejected"]))
        .order_by(Question.id)
    )
    items = [question_to_out(q, True).model_dump() for q in rows.scalars().all()]
    return {"items": items, "total": len(items)}


async def check_duplicates(
    session: AsyncSession, course_id: int, drafts: list[dict[str, Any]], threshold: float = 0.92
) -> tuple[list[dict[str, Any]], int]:
    """与题库已有题目做 embedding 相似度比对（>0.92 视为重复）。"""
    if not drafts:
        return drafts, 0
    rows = await session.execute(
        select(Question).where(Question.course_id == course_id, Question.status != "archived")
    )
    existing = list(rows.scalars().all())
    if not existing:
        return drafts, 0

    embedder = get_embedder()
    existing_vecs = np.asarray(
        await embedder.embed_documents([q.stem for q in existing]), dtype=np.float32
    )
    draft_vecs = await embedder.embed_documents([d.get("stem", "") for d in drafts])

    kept: list[dict[str, Any]] = []
    dropped = 0
    for draft, vec in zip(drafts, draft_vecs, strict=False):
        q = np.asarray(vec, dtype=np.float32)
        norm = float(np.linalg.norm(q))
        if norm > 0:
            q = q / norm
        sims = existing_vecs @ q
        if sims.size and float(sims.max()) > threshold:
            dropped += 1
            continue
        kept.append(draft)
    return kept, dropped


# ---------------- 后台任务 ----------------
@register("generate_questions")
async def generate_questions_task(payload: dict[str, Any]) -> None:
    task_id = payload["task_id"]
    async with AsyncSessionLocal() as session:
        try:
            await _run_generate(session, payload)
        except KnowledgeNotCovered as exc:
            await job_service.fail(session, task_id, exc.message)
            await session.commit()
        except Exception as exc:
            logger.exception("generate_failed", error=str(exc))
            await job_service.fail(session, task_id, str(exc))
            await session.commit()


async def _run_generate(session: AsyncSession, payload: dict[str, Any]) -> None:
    task_id = payload["task_id"]
    course_id = int(payload["course_id"])
    await job_service.update(session, task_id, status="running", progress=10, stage="检索知识库…")
    await session.commit()

    result = await orchestrator.generate_questions(
        session=session,
        course_id=course_id,
        course_name=payload.get("course_name", ""),
        kp_specs=payload.get("kp_specs") or [],
        requirements=payload.get("requirements", ""),
        doc_ids=payload.get("doc_ids"),
        score_per_question=float(payload.get("score_per_question") or DEFAULT_SCORE),
        trace_id=payload.get("trace_id", ""),
    )
    drafts = result["questions"]
    warnings = list(result.get("warnings") or [])

    await job_service.update(session, task_id, progress=70, stage="校验并入库…")
    await session.commit()

    if not drafts:
        message = "；".join(warnings) or "知识库未覆盖所选知识点，未生成任何题目"
        await job_service.fail(session, task_id, message)
        await session.commit()
        return

    drafts, dropped = await check_duplicates(session, course_id, drafts)
    if dropped:
        warnings.append(f"检测到 {dropped} 道与题库重复的题目，已自动丢弃")

    auto_publish = bool(payload.get("auto_publish"))
    status = "published" if auto_publish else "draft"
    created: list[int] = []
    for draft in drafts:
        quality = draft.get("quality") or {}
        question = Question(
            course_id=course_id,
            type=draft.get("type", "single"),
            stem=draft.get("stem", ""),
            options=draft.get("options"),
            answer=draft.get("answer"),
            rubric=draft.get("rubric") or [],
            explanation=draft.get("explanation"),
            difficulty=int(draft.get("difficulty", 3)),
            source_refs=draft.get("source_refs") or [],
            kp_ids=[int(k) for k in (draft.get("kp_ids") or [])],
            status=status if quality.get("citation_ok", True) else "draft",
            quality=quality,
            created_by=None,
            gen_meta={
                "model": settings.LLM_MODEL,
                "provider": settings.LLM_PROVIDER,
                "prompt_version": settings.PROMPT_VERSION,
                "trace_id": payload.get("trace_id"),
            },
        )
        session.add(question)
        await session.flush()
        created.append(question.id)
    await job_service.success(
        session,
        task_id,
        result={
            "created": len(created),
            "question_ids": created,
            "dropped_duplicates": dropped,
            "warnings": warnings,
        },
    )
    await session.commit()
    logger.info("generate_success", course_id=course_id, created=len(created))
