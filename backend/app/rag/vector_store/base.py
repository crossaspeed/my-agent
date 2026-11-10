"""向量库抽象基类（业务代码只依赖它）。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class VectorItem:
    chunk_id: int
    course_id: int
    document_id: int
    vector: list[float]
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class VectorHit:
    chunk_id: int
    score: float


class VectorStore(ABC):
    backend: str = "base"

    @abstractmethod
    async def upsert(self, items: list[VectorItem]) -> int: ...

    @abstractmethod
    async def search(
        self,
        course_id: int,
        vector: list[float],
        top_k: int = 20,
        doc_ids: list[int] | None = None,
    ) -> list[VectorHit]: ...

    @abstractmethod
    async def delete_by_doc(self, document_id: int) -> int: ...

    @abstractmethod
    async def delete_by_course(self, course_id: int) -> int: ...

    @abstractmethod
    async def count(self, course_id: int | None = None) -> int: ...

    async def health(self) -> bool:
        return True
