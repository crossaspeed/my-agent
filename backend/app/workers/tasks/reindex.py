"""重建向量索引任务（换 embedding 模型后必须执行）。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.core.config import settings
from app.core.logging import get_logger
from app.db.base import AsyncSessionLocal
from app.db.models import Document, DocumentChunk
from app.rag import bm25_index
from app.rag.embedder import get_embedder
from app.rag.vector_store import get_vector_store
from app.rag.vector_store.base import VectorItem
from app.services import job_service
from app.workers.registry import register

logger = get_logger(__name__)


@register("reindex_course")
async def reindex_course_task(payload: dict[str, Any]) -> None:
    task_id = payload.get("task_id")
    course_id = payload.get("course_id")
    async with AsyncSessionLocal() as session:
        try:
            if task_id:
                await job_service.update(
                    session, task_id, status="running", progress=5, stage="清理旧向量…"
                )
                await session.commit()
            store = get_vector_store()
            if course_id:
                await store.delete_by_course(int(course_id))

            stmt = select(DocumentChunk).join(
                Document, Document.id == DocumentChunk.document_id
            ).where(Document.status == "ready")
            if course_id:
                stmt = stmt.where(DocumentChunk.course_id == int(course_id))
            chunks = list((await session.execute(stmt)).scalars().all())
            if not chunks:
                if task_id:
                    await job_service.success(session, task_id, result={"chunks": 0})
                    await session.commit()
                return

            embedder = get_embedder()
            batch = settings.EMBEDDING_BATCH_SIZE
            for start in range(0, len(chunks), batch):
                part = chunks[start : start + batch]
                vectors = await embedder.embed_documents([c.content for c in part])
                await store.upsert(
                    [
                        VectorItem(
                            chunk_id=c.id,
                            course_id=c.course_id,
                            document_id=c.document_id,
                            vector=v,
                            payload={"page_no": c.page_no or 0,
                                     "heading_path": c.heading_path or ""},
                        )
                        for c, v in zip(part, vectors, strict=False)
                    ]
                )
                if task_id:
                    await job_service.update(
                        session, task_id,
                        progress=5 + int(90 * min(1.0, (start + batch) / len(chunks))),
                        stage="重建向量中…",
                    )
                    await session.commit()

            bm25_index.invalidate(int(course_id) if course_id else None)
            if task_id:
                await job_service.success(
                    session, task_id, result={"chunks": len(chunks), "backend": store.backend}
                )
                await session.commit()
            logger.info("reindex_done", chunks=len(chunks), course_id=course_id)
        except Exception as exc:
            logger.exception("reindex_failed", error=str(exc))
            if task_id:
                await job_service.fail(session, task_id, str(exc))
                await session.commit()
