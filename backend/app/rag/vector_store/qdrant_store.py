"""Qdrant 向量库实现（可选依赖，演示/生产默认后端）。"""

from __future__ import annotations

import asyncio

from app.core.config import settings
from app.core.exceptions import AppError
from app.rag.vector_store.base import VectorHit, VectorItem, VectorStore


class QdrantVectorStore(VectorStore):
    backend = "qdrant"

    def __init__(self, collection: str | None = None) -> None:
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.http import models as qmodels
        except ImportError as exc:  # pragma: no cover
            raise AppError("未安装 qdrant-client，请 pip install '.[vector]'", code=1009) from exc
        self._qmodels = qmodels
        self._client = QdrantClient(url=settings.QDRANT_URL, timeout=10)
        self.collection = collection or settings.VECTOR_COLLECTION
        if not self._client.collection_exists(self.collection):
            self._client.create_collection(
                collection_name=self.collection,
                vectors_config=qmodels.VectorParams(
                    size=settings.EMBEDDING_DIM, distance=qmodels.Distance.COSINE
                ),
            )

    async def upsert(self, items: list[VectorItem]) -> int:
        def _run() -> int:
            self._client.upsert(
                collection_name=self.collection,
                points=[
                    self._qmodels.PointStruct(
                        id=i.chunk_id,
                        vector=i.vector,
                        payload={
                            "chunk_id": i.chunk_id,
                            "course_id": i.course_id,
                            "document_id": i.document_id,
                            **i.payload,
                        },
                    )
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
        qm = self._qmodels

        def _run() -> list[VectorHit]:
            must = [qm.FieldCondition(key="course_id", match=qm.MatchValue(value=course_id))]
            if doc_ids:
                must.append(
                    qm.FieldCondition(key="document_id", match=qm.MatchAny(any=doc_ids))
                )
            res = self._client.search(
                collection_name=self.collection,
                query_vector=vector,
                limit=top_k,
                query_filter=qm.Filter(must=must),
            )
            return [VectorHit(chunk_id=int(p.id), score=float(p.score)) for p in res]

        return await asyncio.to_thread(_run)

    async def delete_by_doc(self, document_id: int) -> int:
        qm = self._qmodels

        def _run() -> int:
            self._client.delete(
                collection_name=self.collection,
                points_selector=qm.FilterSelector(
                    filter=qm.Filter(
                        must=[qm.FieldCondition(key="document_id", match=qm.MatchValue(value=document_id))]
                    )
                ),
            )
            return 0

        return await asyncio.to_thread(_run)

    async def delete_by_course(self, course_id: int) -> int:
        qm = self._qmodels

        def _run() -> int:
            self._client.delete(
                collection_name=self.collection,
                points_selector=qm.FilterSelector(
                    filter=qm.Filter(
                        must=[qm.FieldCondition(key="course_id", match=qm.MatchValue(value=course_id))]
                    )
                ),
            )
            return 0

        return await asyncio.to_thread(_run)

    async def count(self, course_id: int | None = None) -> int:
        def _run() -> int:
            info = self._client.get_collection(self.collection)
            return int(getattr(info, "points_count", 0) or 0)

        return await asyncio.to_thread(_run)
