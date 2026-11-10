"""认证服务。"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BadRequest, Conflict, Unauthorized
from app.core.security import create_access_token, hash_password, verify_password
from app.db.models import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenOut, UserOut

TEACHER_INVITE_CODE = "TEACHER2026"  # 演示用邀请码；生产应从配置/DB 读取


async def register(session: AsyncSession, req: RegisterRequest) -> TokenOut:
    exists = await session.execute(select(User).where(User.username == req.username))
    if exists.scalar_one_or_none() is not None:
        raise Conflict("用户名已存在")
    if req.email:
        dup = await session.execute(select(User).where(User.email == req.email))
        if dup.scalar_one_or_none() is not None:
            raise Conflict("邮箱已被注册")

    role = "student"
    if req.role == "teacher":
        if req.invite_code != TEACHER_INVITE_CODE:
            raise BadRequest("教师注册需要正确的邀请码")
        role = "teacher"

    # 系统首个用户自动成为 admin（避免初始无管理入口）
    count = await session.scalar(select(func.count()).select_from(User))
    if not count:
        role = "admin"

    user = User(
        username=req.username,
        email=req.email,
        real_name=req.real_name,
        password_hash=hash_password(req.password),
        role=role,
    )
    session.add(user)
    await session.flush()
    return _token_for(user)


async def login(session: AsyncSession, req: LoginRequest) -> TokenOut:
    row = await session.execute(select(User).where(User.username == req.username))
    user = row.scalar_one_or_none()
    if user is None or not verify_password(req.password, user.password_hash):
        raise Unauthorized("用户名或密码错误")
    if not user.is_active:
        raise Unauthorized("账号已被禁用")
    return _token_for(user)


async def change_password(session: AsyncSession, user: User, old: str, new: str) -> None:
    if not verify_password(old, user.password_hash):
        raise BadRequest("原密码不正确")
    user.password_hash = hash_password(new)
    session.add(user)


def _token_for(user: User) -> TokenOut:
    token = create_access_token(user.id, user.role)
    return TokenOut(
        access_token=token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserOut.model_validate(user),
    )
