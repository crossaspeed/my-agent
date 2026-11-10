"""Agent 运行上下文（随 state["_ctx"] 传入，避免图编译时绑定请求级会话）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.rag.retriever import RetrievedChunk


@dataclass
class AgentContext:
    session: AsyncSession
    course_id: int
    course_name: str = ""
    trace_id: str = ""
    retrieved: dict[int, RetrievedChunk] = field(default_factory=dict)
    user_id: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def remember(self, chunks: list[RetrievedChunk]) -> None:
        for chunk in chunks:
            self.retrieved[chunk.chunk_id] = chunk
