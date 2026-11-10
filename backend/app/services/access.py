"""课程级权限（水平越权的唯一判定入口，所有服务层必须经过这里）。"""

from __future__ import annotations

from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import Forbidden, NotFound
from app.db.models import Course, CourseMember, User

Need = Literal["member", "teacher", "owner"]


async def get_course_role(session: AsyncSession, course_id: int, user: User) -> tuple[Course, str]:
    course = await session.get(Course, course_id)
    if course is None:
        raise NotFound("课程不存在")
    if user.role == "admin" or course.owner_id == user.id:
        return course, "owner"
    row = await session.execute(
        select(CourseMember).where(
            CourseMember.course_id == course_id, CourseMember.user_id == user.id
        )
    )
    member = row.scalar_one_or_none()
    if member is None:
        raise Forbidden("您不是该课程成员")
    return course, member.role


async def require_course(
    session: AsyncSession, course_id: int, user: User, need: Need = "member"
) -> tuple[Course, str]:
    course, role = await get_course_role(session, course_id, user)
    if need == "owner" and role != "owner":
        raise Forbidden("该操作仅课程创建者可用")
    if need == "teacher" and role not in ("owner", "teacher"):
        raise Forbidden("该操作仅教师可用")
    return course, role
