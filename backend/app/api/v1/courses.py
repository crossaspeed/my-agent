"""课程、成员、知识点路由。"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.core.deps import CurrentUser, SessionDep, TeacherUser
from app.schemas.common import ok
from app.schemas.course import (
    CourseCreate,
    CourseUpdate,
    KnowledgePointAutoRequest,
    KnowledgePointCreate,
    KnowledgePointUpdate,
    MemberAddRequest,
)
from app.services import course_service

router = APIRouter(tags=["课程"])


@router.post("/courses", summary="创建课程（教师）")
async def create_course(req: CourseCreate, user: TeacherUser, session: SessionDep):
    """仅教师（或管理员）可创建课程。"""
    return ok(await course_service.create_course(session, user, req))


@router.get("/courses", summary="我的课程（教师=拥有，学生=已加入）")
async def list_courses(user: CurrentUser, session: SessionDep):
    return ok(await course_service.list_courses(session, user))


@router.get("/courses/{course_id}", summary="课程详情（含统计）")
async def get_course(course_id: int, user: CurrentUser, session: SessionDep):
    return ok(await course_service.get_detail(session, course_id, user))


@router.patch("/courses/{course_id}", summary="修改课程配置（创建者）")
async def update_course(
    course_id: int, req: CourseUpdate, user: CurrentUser, session: SessionDep
):
    return ok(await course_service.update_course(session, course_id, user, req))


@router.delete("/courses/{course_id}", summary="删除课程（创建者，含全部课件/题库/试卷/作答）")
async def delete_course(course_id: int, user: CurrentUser, session: SessionDep):
    name = await course_service.delete_course(session, course_id, user)
    return ok(None, message=f"课程「{name}」及其课件、题库、试卷、作答记录已删除")


@router.post("/courses/{course_id}/members", summary="批量添加学生")
async def add_members(
    course_id: int, req: MemberAddRequest, user: CurrentUser, session: SessionDep
):
    return ok(await course_service.add_members(session, course_id, user, req.usernames))


@router.get("/courses/{course_id}/members", summary="课程成员列表")
async def list_members(course_id: int, user: CurrentUser, session: SessionDep):
    return ok(await course_service.list_members(session, course_id, user))


@router.get("/courses/{course_id}/knowledge-points", summary="知识点树")
async def kp_tree(course_id: int, user: CurrentUser, session: SessionDep):
    return ok(await course_service.get_kp_tree(session, course_id, user))


@router.post("/courses/{course_id}/knowledge-points", summary="新建知识点")
async def create_kp(
    course_id: int, req: KnowledgePointCreate, user: CurrentUser, session: SessionDep
):
    return ok(await course_service.create_kp(session, course_id, user, req))


@router.post("/courses/{course_id}/knowledge-points:auto", summary="从知识库自动抽取知识点树")
async def auto_kp(
    course_id: int,
    req: KnowledgePointAutoRequest,
    user: CurrentUser,
    session: SessionDep,
):
    return ok(
        await course_service.auto_extract_kps(session, course_id, user, req.max_points)
    )


@router.patch("/knowledge-points/{kp_id}", summary="修改知识点")
async def update_kp(
    kp_id: int, req: KnowledgePointUpdate, user: CurrentUser, session: SessionDep
):
    return ok(await course_service.update_kp(session, kp_id, user, req))


@router.delete("/knowledge-points/{kp_id}", summary="删除知识点")
async def delete_kp(
    kp_id: int, user: CurrentUser, session: SessionDep, force: bool = Query(default=False)
):
    await course_service.delete_kp(session, kp_id, user)
    return ok(None, message="已删除" if force else "已删除")
