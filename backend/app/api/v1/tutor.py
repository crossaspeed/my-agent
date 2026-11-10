"""导学路由（SSE 流式）。"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.core.deps import CurrentUser, SessionDep
from app.schemas.common import ok
from app.schemas.tutor import TutorSendRequest, TutorSessionCreate
from app.services import tutor_service

router = APIRouter(prefix="/tutor", tags=["导学"])

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


@router.post("/sessions", summary="创建导学会话（返回开场讲解）")
async def create_session(req: TutorSessionCreate, user: CurrentUser, session: SessionDep):
    return ok(
        await tutor_service.create_session(
            session, user, req.answer_id, req.course_id, req.question_id
        )
    )


@router.get("/sessions", summary="我的导学会话列表")
async def list_sessions(user: CurrentUser, session: SessionDep):
    return ok(await tutor_service.list_sessions(session, user))


@router.get("/sessions/{session_id}", summary="会话详情与历史消息")
async def get_session(session_id: int, user: CurrentUser, session: SessionDep):
    return ok(await tutor_service.get_session(session, session_id, user))


@router.post("/sessions/{session_id}/messages", summary="发送消息（SSE 流式）")
async def send_message(
    session_id: int, req: TutorSendRequest, user: CurrentUser
):
    return StreamingResponse(
        tutor_service.stream_message(session_id, user, req),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.delete("/sessions/{session_id}", summary="删除会话")
async def delete_session(session_id: int, user: CurrentUser, session: SessionDep):
    await tutor_service.delete_session(session, session_id, user)
    return ok(None, message="会话已删除")
