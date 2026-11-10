"""向量库工厂：配置切换，失败自动降级到本地实现。"""

from __future__ import annotations

from functools import lru_cache

from app.core.config import settings
from app.core.logging import get_logger
from app.rag.vector_store.base import VectorStore
from app.rag.vector_store.local_store import LocalVectorStore

logger = get_logger(__name__)


@lru_cache(maxsize=4)
def get_vector_store() -> VectorStore:
    backend = settings.VECTOR_BACKEND.lower()
    if backend == "chroma":
        try:
            from app.rag.vector_store.chroma_store import ChromaVectorStore

            return ChromaVectorStore()
        except Exception as exc:  # pragma: no cover - 依赖外部
            logger.warning("vector_store_fallback", backend="chroma", error=str(exc))
    if backend == "qdrant":
        try:
            from app.rag.vector_store.qdrant_store import QdrantVectorStore

            return QdrantVectorStore()
        except Exception as exc:  # pragma: no cover - 依赖外部
            logger.warning("vector_store_fallback", backend="qdrant", error=str(exc))
    return LocalVectorStore()


def reset_vector_store() -> None:
    get_vector_store.cache_clear()
