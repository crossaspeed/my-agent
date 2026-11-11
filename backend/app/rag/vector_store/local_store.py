"""本地向量库实现：numpy 暴力检索 + JSON 落盘。

用途：开发/答辩离线环境默认后端（零外部依赖）。万级 chunk 下检索 <20ms，
规模再大应切换 Qdrant。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import numpy as np

from app.core.config import settings
from app.core.logging import get_logger
from app.rag.vector_store.base import VectorHit, VectorItem, VectorStore

logger = get_logger(__name__)


class LocalVectorStore(VectorStore):
    backend = "local"

    def __init__(self, path: Path | None = None, collection: str | None = None) -> None:
        name = collection or settings.VECTOR_COLLECTION
        base_dir = settings.resolve_path(settings.VECTOR_DIR)
        base_dir.mkdir(parents=True, exist_ok=True)
        self.path = path or (base_dir / f"{name}.json")
        self._lock = threading.RLock()
        self._items: dict[int, dict[str, Any]] | None = None
        self._cache: dict[int | None, tuple[np.ndarray, list[int]]] = {}
        # 落盘文件的 mtime：解析任务在 worker 进程写盘，API 进程必须能感知到变化，
        # 否则「刚上传的课件搜不到」（两进程各自持有内存副本）
        self._mtime_ns: int = 0
        self._size: int = -1

    # ---------- 持久化 ----------
    def _stat(self) -> tuple[int, int]:
        try:
            st = self.path.stat()
            return st.st_mtime_ns, st.st_size
        except OSError:
            return 0, -1

    def _load(self, force: bool = False) -> dict[int, dict[str, Any]]:
        with self._lock:
            mtime, size = self._stat()
            if (
                not force
                and self._items is not None
                and mtime == self._mtime_ns
                and size == self._size
            ):
                return self._items
            if self._items is not None:  # 文件被其他进程更新 → 丢弃内存副本与矩阵缓存
                logger.info("vector_store_reloaded", path=str(self.path), chunks=len(self._items))
                self._cache.clear()
                self._items = None
            if self.path.exists():
                try:
                    raw = json.loads(self.path.read_text(encoding="utf-8"))
                    self._items = {int(k): v for k, v in raw.get("items", {}).items()}
                except (json.JSONDecodeError, OSError) as exc:
                    logger.warning("vector_store_corrupt", error=str(exc), path=str(self.path))
                    self._items = {}
            else:
                self._items = {}
            self._mtime_ns, self._size = mtime, size
            return self._items

    def _flush(self) -> None:
        with self._lock:
            assert self._items is not None
            payload = {"dim": settings.EMBEDDING_DIM, "items": self._items}
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
            self._mtime_ns, self._size = self._stat()
            self._cache.clear()

    @contextmanager
    def _file_lock(self, timeout: float = 15.0):
        """跨进程互斥：API 与 worker 都会写这份文件，不加锁会互相覆盖（丢向量）。"""
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        deadline = time.monotonic() + timeout
        fd = -1
        while True:
            try:
                fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
                break
            except FileExistsError:
                if time.monotonic() > deadline:
                    raise TimeoutError(f"等待向量库写锁超时: {lock_path}") from None
                time.sleep(0.02)
            except FileNotFoundError:
                lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            yield
        finally:
            try:
                os.close(fd)
            finally:
                with contextlib.suppress(OSError):
                    os.unlink(lock_path)

    # ---------- 接口实现 ----------
    async def upsert(self, items: list[VectorItem]) -> int:
        def _run() -> int:
            with self._file_lock():
                # 必须重载：可能已被其他进程写入，直接用内存副本会覆盖掉别人的数据
                store = self._load(force=True)
                return self._upsert_locked(store, items)

        return await asyncio.to_thread(_run)

    def _upsert_locked(
        self, store: dict[int, dict[str, Any]], items: list[VectorItem]
    ) -> int:
        for item in items:
            store[item.chunk_id] = {
                "course_id": item.course_id,
                "document_id": item.document_id,
                "vector": [round(float(v), 6) for v in item.vector],
                "payload": item.payload,
            }
        self._flush()
        return len(items)

    async def search(
        self,
        course_id: int,
        vector: list[float],
        top_k: int = 20,
        doc_ids: list[int] | None = None,
    ) -> list[VectorHit]:
        def _run() -> list[VectorHit]:
            matrix, ids, docs = self._matrix(course_id)
            if not ids:
                return []
            query = np.asarray(vector, dtype=np.float32)
            norm = float(np.linalg.norm(query))
            if norm == 0:
                return []
            query = query / norm
            scores = matrix @ query
            order = np.argsort(-scores)
            hits: list[VectorHit] = []
            for idx in order[: max(top_k * 5, top_k)]:
                if doc_ids and docs[idx] not in doc_ids:
                    continue
                hits.append(VectorHit(chunk_id=int(ids[idx]), score=float(scores[idx])))
                if len(hits) >= top_k:
                    break
            return hits

        return await asyncio.to_thread(_run)

    def _matrix(self, course_id: int | None) -> tuple[np.ndarray, list[int], list[int]]:
        with self._lock:
            # 先探一次文件状态：别的进程写入后这里会清空 _cache，
            # 否则新上传的课件在向量检索里一直不可见（旧实现直接命中缓存返回）
            self._load()
            if course_id in self._cache:
                matrix, ids = self._cache[course_id]
                docs = [self._load()[cid]["document_id"] for cid in ids]
                return matrix, ids, docs
            store = self._load()
            ids: list[int] = []
            vectors: list[list[float]] = []
            docs: list[int] = []
            for chunk_id, item in store.items():
                if course_id is not None and item.get("course_id") != course_id:
                    continue
                vec = item.get("vector") or []
                if len(vec) != settings.EMBEDDING_DIM:
                    continue  # 维度不一致（换过 embedding 模型）→ 需 reindex
                ids.append(chunk_id)
                vectors.append(vec)
                docs.append(int(item.get("document_id", 0)))
            matrix = np.asarray(vectors, dtype=np.float32) if vectors else np.zeros((0, settings.EMBEDDING_DIM), dtype=np.float32)
            self._cache[course_id] = (matrix, ids)
            return matrix, ids, docs

    async def delete_by_doc(self, document_id: int) -> int:
        def _run() -> int:
            with self._file_lock():
                store = self._load(force=True)
                to_delete = [
                    cid for cid, v in store.items() if v.get("document_id") == document_id
                ]
                for cid in to_delete:
                    store.pop(cid, None)
                if to_delete:
                    self._flush()
                return len(to_delete)

        return await asyncio.to_thread(_run)

    async def delete_by_course(self, course_id: int) -> int:
        def _run() -> int:
            with self._file_lock():
                store = self._load(force=True)
            to_delete = [cid for cid, v in store.items() if v.get("course_id") == course_id]
            for cid in to_delete:
                store.pop(cid, None)
            if to_delete:
                self._flush()
            return len(to_delete)

        return await asyncio.to_thread(_run)

    async def count(self, course_id: int | None = None) -> int:
        def _run() -> int:
            store = self._load()
            if course_id is None:
                return len(store)
            return sum(1 for v in store.values() if v.get("course_id") == course_id)

        return await asyncio.to_thread(_run)

    async def health(self) -> bool:
        try:
            self._load()
            return True
        except Exception:  # pragma: no cover
            return False
