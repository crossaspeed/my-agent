"""数据库引擎与会话工厂。"""

from __future__ import annotations

from collections.abc import AsyncIterator
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


engine: AsyncEngine = create_async_engine(
    normalize_sqlite_url(settings.DATABASE_URL),
    echo=settings.DB_ECHO,
    future=True,
    **_engine_kwargs(),
)

if settings.is_sqlite:
    from sqlalchemy import event

    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):  # type: ignore[no-untyped-def]
        """WAL + busy_timeout：允许「一个写 + 多个读」并发，避免后台任务写审计表时锁库。"""
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=8000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

# 审计专用引擎：llm_calls 是分析数据，写入失败/短暂锁库不得阻塞主流程，
# 因此单独建连接池并设置很短的 busy_timeout（仅 SQLite 需要）。
_audit_engine: AsyncEngine = create_async_engine(
    normalize_sqlite_url(settings.DATABASE_URL), echo=False, future=True, **_engine_kwargs()
)
if settings.is_sqlite:
    from sqlalchemy import event

    @event.listens_for(_audit_engine.sync_engine, "connect")
    def _audit_pragmas(dbapi_connection, _record):  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=300")
        cursor.close()

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
