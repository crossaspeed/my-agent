"""数据库引擎与会话工厂。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import DateTime, func
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import NullPool

from app.core.config import settings


def normalize_sqlite_url(url: str) -> str:
    """把相对 SQLite 路径固定到项目根目录，并确保父目录存在。"""
    for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
        if url.startswith(prefix):
            raw = url[len(prefix) :]
            if raw.startswith(":memory:"):
                return url
            path = Path(raw)
            if not path.is_absolute():
                path = settings.resolve_path(raw)
            path.parent.mkdir(parents=True, exist_ok=True)
            return f"{prefix}{path.as_posix()}"
    return url


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), default=lambda: datetime.now(UTC)
    )


def _engine_kwargs() -> dict[str, Any]:
    if settings.is_sqlite:
        return {"connect_args": {"check_same_thread": False}}
    return {
        "pool_size": settings.DB_POOL_SIZE,
        "max_overflow": settings.DB_MAX_OVERFLOW,
        "pool_pre_ping": True,
    }


def _attach_sqlite_pragmas(target: AsyncEngine, busy_timeout: int) -> None:
    """SQLite 连接级 PRAGMA；PG 下无需处理。"""
    if not settings.is_sqlite:
        return

    from sqlalchemy import event

    @event.listens_for(target.sync_engine, "connect")
    def _pragmas(dbapi_connection, _record):  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute(f"PRAGMA busy_timeout={busy_timeout}")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()


def _new_isolated_engine(busy_timeout: int = 8000) -> AsyncEngine:
    """一次性引擎：NullPool 不保留连接，用完即销毁。"""
    isolated = create_async_engine(
        normalize_sqlite_url(settings.DATABASE_URL),
        echo=settings.DB_ECHO,
        future=True,
        poolclass=NullPool,
        connect_args={"check_same_thread": False} if settings.is_sqlite else {},
    )
    _attach_sqlite_pragmas(isolated, busy_timeout=busy_timeout)
    return isolated


@asynccontextmanager
async def task_session(busy_timeout: int = 8000) -> AsyncIterator[AsyncSession]:
    """后台任务 / 一次性写入专用会话。

    为什么不能复用全局 `AsyncSessionLocal`：
    Celery（prefork）与进程内线程池的执行方式都是「一个任务一次 asyncio.run」，
    每次都会**新建事件循环**；而 asyncpg 连接在创建时就绑定了当时的事件循环，
    复用全局连接池会抛 `Future attached to a different loop`（表现为课件解析失败、
    llm_calls 审计静默丢数据）。

    这里每个任务新建独立引擎、使用 NullPool、结束即 dispose：
    连接不跨任务存活，也就不存在跨循环复用。
    """
    isolated = _new_isolated_engine(busy_timeout)
    try:
        maker = async_sessionmaker(isolated, expire_on_commit=False, class_=AsyncSession)
        async with maker() as session:
            yield session
    finally:
        await isolated.dispose()


engine: AsyncEngine = create_async_engine(
    normalize_sqlite_url(settings.DATABASE_URL),
    echo=settings.DB_ECHO,
    future=True,
    **_engine_kwargs(),
)
_attach_sqlite_pragmas(engine, busy_timeout=8000)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

# 审计专用引擎：llm_calls 是分析数据，写入失败/短暂锁库不得阻塞主流程，
# 因此单独建连接池并设置很短的 busy_timeout（仅 SQLite 需要）。
_audit_engine: AsyncEngine = create_async_engine(
    normalize_sqlite_url(settings.DATABASE_URL), echo=False, future=True, **_engine_kwargs()
)
_attach_sqlite_pragmas(_audit_engine, busy_timeout=300)

AuditSessionLocal = async_sessionmaker(_audit_engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_models() -> None:
    """开发环境快捷建表（生产走 alembic upgrade head）。"""
    from app.db import models  # noqa: F401  确保模型已注册

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
