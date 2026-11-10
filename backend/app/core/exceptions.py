"""业务异常与全局异常处理器。

约定：异常只携带业务码与用户可读信息，堆栈只写日志，绝不返回给前端。
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger

logger = get_logger(__name__)


class AppError(Exception):
    """所有业务异常的基类。"""

    code: int = 5000
    http_status: int = 500
    message: str = "服务器内部错误"

    def __init__(self, message: str | None = None, *, code: int | None = None,
                 detail: Any = None) -> None:
        self.message = message or self.message
        if code is not None:
            self.code = code
        self.detail = detail
        super().__init__(self.message)

    def to_response(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "data": self.detail,
        }


class BadRequest(AppError):
    code = 1001
    http_status = 400
    message = "请求参数不合法"


class Unauthorized(AppError):
    code = 1002
    http_status = 401
    message = "未登录或登录已过期"


class Forbidden(AppError):
    code = 1003
    http_status = 403
    message = "无权访问该资源"


class NotFound(AppError):
    code = 1004
    http_status = 404
    message = "资源不存在"


class Conflict(AppError):
    code = 1005
    http_status = 409
    message = "资源冲突"


class ParseFailed(AppError):
    code = 1010
    http_status = 422
    message = "文档解析失败"


class KnowledgeNotCovered(AppError):
    """检索无据：绝不编题/编答案。"""

    code = 1011
    http_status = 422
    message = "知识库未覆盖该知识点，请补充课件或调整知识点"


class RateLimited(AppError):
    code = 1029
    http_status = 429
    message = "请求过于频繁，请稍后再试"


class LLMTimeout(AppError):
    code = 5001
    http_status = 504
    message = "模型响应超时，请稍后重试"


class LLMUnavailable(AppError):
    code = 5002
    http_status = 503
    message = "模型服务暂不可用，已触发熔断"


class AgentError(AppError):
    code = 5003
    http_status = 500
    message = "智能体执行失败"

    def __init__(self, node: str, message: str) -> None:
        super().__init__(f"[{node}] {message}", detail={"node": node})
        self.node = node


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        if exc.http_status >= 500:
            logger.error("app_error", code=exc.code, message=exc.message)
        return JSONResponse(status_code=exc.http_status, content=exc.to_response())

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.status_code * 10, "message": str(exc.detail), "data": None},
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "code": 4220,
                "message": "参数校验失败",
                "data": [
                    {"loc": list(e.get("loc", [])), "msg": e.get("msg", "")} for e in exc.errors()
                ],
            },
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        trace_id = getattr(request.state, "trace_id", "")
        logger.exception("unhandled_error", trace_id=trace_id, error=str(exc))
        return JSONResponse(
            status_code=500,
            content={"code": 9999, "message": f"服务器内部错误（trace_id={trace_id}）", "data": None},
        )
