"""认证路由。"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.deps import CurrentUser, SessionDep
from app.schemas.auth import ChangePasswordRequest, LoginRequest, RegisterRequest
from app.schemas.common import ok
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/register", summary="注册（默认学生；首个用户自动成为管理员）")
async def register(req: RegisterRequest, session: SessionDep):
    return ok(await auth_service.register(session, req))


@router.post("/login", summary="登录，返回 JWT")
async def login(req: LoginRequest, session: SessionDep):
    return ok(await auth_service.login(session, req))


@router.get("/me", summary="当前登录用户")
async def me(user: CurrentUser):
    return ok(user)


@router.post("/change-password", summary="修改密码")
async def change_password(req: ChangePasswordRequest, user: CurrentUser, session: SessionDep):
    await auth_service.change_password(session, user, req.old_password, req.new_password)
    return ok(None, message="密码已更新")
