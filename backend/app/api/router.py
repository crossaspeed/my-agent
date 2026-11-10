"""路由汇总注册。"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import admin, auth, courses, documents, jobs, papers, questions, tutor
from app.core.config import settings

api_router = APIRouter(prefix=settings.API_PREFIX)
api_router.include_router(auth.router)
api_router.include_router(courses.router)
api_router.include_router(documents.router)
api_router.include_router(questions.router)
api_router.include_router(papers.router)
api_router.include_router(tutor.router)
api_router.include_router(jobs.router)
api_router.include_router(admin.router)

__all__ = ["api_router"]
