"""FastAPI 应用入口：CORS、trace 中间件、异常处理、健康检查。"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import get_logger, setup_logging
from app.db.base import AsyncSessionLocal, init_models
from app.workers.registry import load_all
from app.workers.runner import shutdown

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    setup_logging()
    load_all()
    if settings.AUTO_CREATE_TABLES:
        await init_models()
        logger.info("tables_ready", url=settings.DATABASE_URL.split("://")[0])
    try:
        from app.services.document_service import reconcile_stuck_documents

        async with AsyncSessionLocal() as session:
            fixed = await reconcile_stuck_documents(session)
            await session.commit()
            if fixed:
                logger.warning("stuck_documents_reset", count=fixed)
    except Exception as exc:  # pragma: no cover
        logger.warning("startup_reconcile_failed", error=str(exc))
    logger.info(
        "app_started",
        env=settings.APP_ENV,
        llm=settings.LLM_PROVIDER,
        embedding=settings.EMBEDDING_PROVIDER,
        vector=settings.VECTOR_BACKEND,
        queue="celery" if settings.USE_CELERY else "thread",
    )
    yield
    shutdown()
    logger.info("app_stopped")


def create_app() -> FastAPI:
    setup_logging()
    app = FastAPI(
        title=f"{settings.APP_NAME} API",
        description="基于多智能体协同的课程自主测评与导学系统（course-agent）",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Trace-Id"],
    )

    @app.middleware("http")
    async def trace_middleware(request: Request, call_next: Any) -> Any:
        trace_id = request.headers.get("X-Trace-Id") or uuid.uuid4().hex[:16]
        request.state.trace_id = trace_id
        started = time.perf_counter()
        response = await call_next(request)
        latency_ms = int((time.perf_counter() - started) * 1000)
        response.headers["X-Trace-Id"] = trace_id
        if not request.url.path.startswith(("/docs", "/openapi", "/redoc")):
            logger.info(
                "http_request",
                trace_id=trace_id,
                method=request.method,
                route=request.url.path,
                status=response.status_code,
                latency_ms=latency_ms,
            )
        return response

    register_exception_handlers(app)
    app.include_router(api_router)

    @app.get("/health", tags=["系统"], summary="存活探针")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "app": settings.APP_NAME, "version": "1.0.0",
                "env": settings.APP_ENV}

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {"name": settings.APP_NAME, "docs": "/docs", "api": settings.API_PREFIX}

    return app


app = create_app()
