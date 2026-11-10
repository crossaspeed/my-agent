"""题目生成、题库与审核路由。"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.core.deps import CurrentUser, SessionDep
from app.schemas.common import ok
from app.schemas.question import (
    BatchReviewRequest,
    GenerateRequest,
    QuestionUpdate,
    ReviewRequest,
)
from app.services import question_service

router = APIRouter(tags=["题目"])


@router.post("/courses/{course_id}/questions:generate", summary="出题官异步出题")
async def generate(
    course_id: int, req: GenerateRequest, user: CurrentUser, session: SessionDep
):
    return ok(await question_service.generate_questions(session, course_id, user, req))


@router.get("/courses/{course_id}/questions", summary="题库列表")
async def list_questions(
    course_id: int,
    user: CurrentUser,
    session: SessionDep,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    status: str | None = None,
    type: str | None = Query(default=None),
    kp_id: int | None = None,
    keyword: str | None = None,
):
    return ok(
        await question_service.list_questions(
            session, course_id, user, page=page, size=size, status=status,
            qtype=type, kp_id=kp_id, keyword=keyword,
        )
    )


@router.get("/courses/{course_id}/questions/review-queue", summary="待审核题目")
async def review_queue(course_id: int, user: CurrentUser, session: SessionDep):
    return ok(await question_service.review_queue(session, course_id, user))


@router.get("/questions/{question_id}", summary="题目详情")
async def get_question(question_id: int, user: CurrentUser, session: SessionDep):
    return ok(await question_service.get_question(session, question_id, user))


@router.patch("/questions/{question_id}", summary="编辑题目")
async def update_question(
    question_id: int, req: QuestionUpdate, user: CurrentUser, session: SessionDep
):
    return ok(await question_service.update_question(session, question_id, user, req))


@router.post("/questions/{question_id}:review", summary="审核单题（通过/驳回）")
async def review(
    question_id: int, req: ReviewRequest, user: CurrentUser, session: SessionDep
):
    return ok(
        await question_service.review_question(
            session, question_id, user, req.action, req.note
        )
    )


@router.post("/questions:batch-review", summary="批量审核")
async def batch_review(req: BatchReviewRequest, user: CurrentUser, session: SessionDep):
    return ok(
        await question_service.batch_review(session, user, req.ids, req.action, req.note)
    )


@router.delete("/questions/{question_id}", summary="归档题目（软删）")
async def archive(question_id: int, user: CurrentUser, session: SessionDep):
    await question_service.archive_question(session, question_id, user)
    return ok(None, message="题目已归档")
