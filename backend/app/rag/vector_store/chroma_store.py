"""Chroma 向量库实现（可选依赖）。业务代码只依赖 VectorStore 抽象。"""

from __future__ import annotations

import asyncio
from typing import Any

from app.core.config import settings
from app.core.exceptions import AppError
from app.rag.vector_store.base import VectorHit, VectorItem, VectorStore


class ChromaVectorStore(VectorStore):
    backend = "chroma"

    def __init__(self, collection: str | None = None) -> None:
        try:
            import chromadb
        except ImportError as exc:  # pragma: no cover
            raise AppError("未安装 chromadb，请 pip install '.[vector]'", code=1009) from exc
        self._client = chromadb.PersistentClient(path=str(settings.resolve_path(settings.CHROMA_DIR)))
        self._collection = self._client.get_or_create_collection(
            name=collection or settings.VECTOR_COLLECTION,
            metadata={"hnsw:space": "cosine", "dim": settings.EMBEDDING_DIM},
        )

    async def upsert(self, items: list[VectorItem]) -> int:
        def _run() -> int:
            self._collection.upsert(
                ids=[str(i.chunk_id) for i in items],
                embeddings=[i.vector for i in items],
                metadatas=[
                    {"course_id": i.course_id, "document_id": i.document_id, **i.payload}
                    for i in items
                ],
            )
            return len(items)

        return await asyncio.to_thread(_run)

    async def search(
        self,
        course_id: int,
        vector: list[float],
        top_k: int = 20,
        doc_ids: list[int] | None = None,
    ) -> list[VectorHit]:
        def _run() -> list[VectorHit]:
            where: dict[str, Any] = {"course_id": course_id}
            if doc_ids:
                where = {"$and": [{"course_id": course_id}, {"document_id": {"$in": doc_ids}}]}
            res = self._collection.query(
                query_embeddings=[vector], n_results=top_k, where=where,
                include=["distances"],
            )
            ids = (res.get("ids") or [[]])[0]
            distances = (res.get("distances") or [[]])[0]
            return [VectorHit(chunk_id=int(cid), score=1.0 - float(dist))
                    for cid, dist in zip(ids, distances, strict=False)]

        return await asyncio.to_thread(_run)

    async def delete_by_doc(self, document_id: int) -> int:
        def _run() -> int:
            before = self._collection.count()
            self._collection.delete(where={"document_id": document_id})
            return max(0, before - self._collection.count())

        return await asyncio.to_thread(_run)

    async def delete_by_course(self, course_id: int) -> int:
        def _run() -> int:
            before = self._collection.count()
            self._collection.delete(where={"course_id": course_id})
            return max(0, before - self._collection.count())

        return await asyncio.to_thread(_run)

    async def count(self, course_id: int | None = None) -> int:
        def _run() -> int:
            if course_id is None:
                return self._collection.count()
            res = self._collection.get(where={"course_id": course_id}, include=[])
            return len(res.get("ids") or [])

        return await asyncio.to_thread(_run)
