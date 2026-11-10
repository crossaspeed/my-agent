"""FastAPI 依赖：DB 会话、当前用户、角色守卫。"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import Forbidden, Unauthorized
from app.core.security import decode_token
from app.db.base import get_session
from app.db.models import User

bearer_scheme = HTTPBearer(auto_error=False, description="Bearer <JWT>")

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> User:
    if credentials is None or not credentials.credentials:
        raise Unauthorized("缺少访问令牌")
    payload = decode_token(credentials.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise Unauthorized("无效的访问令牌")
    user = await session.get(User, int(user_id))
    if user is None or not user.is_active:
        raise Unauthorized("用户不存在或已被禁用")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(*roles: str) -> Callable[..., Coroutine[Any, Any, User]]:
    """角色守卫。admin 视为拥有全部权限。"""

    async def _guard(user: CurrentUser) -> User:
        if user.role == "admin" or user.role in roles:
            return user
        raise Forbidden(f"该操作需要角色：{'/'.join(roles)}")

    return _guard


TeacherUser = Annotated[User, Depends(require_role("teacher"))]


def parse_bearer_token(authorization: str | None) -> dict[str, Any]:
    """供 SSE 等非标准 Header 场景复用（EventSource 无法带 Header 时用 query token）。"""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise Unauthorized("缺少访问令牌")
    return decode_token(authorization.split(" ", 1)[1].strip())


async def load_user_by_id(session: AsyncSession, user_id: int) -> User | None:
    result = await session.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()
