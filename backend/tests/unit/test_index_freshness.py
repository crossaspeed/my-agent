"""索引新鲜度测试：跨进程写入后，检索侧必须能感知到语料变化。

背景：课件由 Celery worker 进程解析入库并写向量文件，而检索发生在 API 进程。
两边各自持有内存缓存（numpy 矩阵 / BM25 语料），若不校验变化，
就会出现「刚上传的课件搜不到」，最长滞后 10 分钟。
"""

from __future__ import annotations

import json

import pytest

from app.rag.bm25_index import CourseBM25, get_index


@pytest.fixture(autouse=True)
def _clean_bm25_cache():
    from app.rag import bm25_index

    bm25_index.invalidate(None)
    yield
    bm25_index.invalidate(None)


@pytest.mark.asyncio
async def test_bm25_returns_cached_index_when_signature_unchanged(db, monkeypatch):
    from app.rag import bm25_index

    fake = CourseBM25([1], [["握手"]], signature=(1, 1))

    async def same_signature(_session, _course_id):
        return (1, 1)

    monkeypatch.setattr(bm25_index, "_corpus_signature", same_signature)
    bm25_index._cache[999] = fake
    assert await get_index(db, 999) is fake


@pytest.mark.asyncio
async def test_bm25_rebuilds_when_signature_changes(db, monkeypatch):
    from app.rag import bm25_index

    stale = CourseBM25([1], [["握手"]], signature=(1, 1))

    async def grown_signature(_session, _course_id):
        return (2, 7)  # 语料被别的进程加了一个 chunk

    monkeypatch.setattr(bm25_index, "_corpus_signature", grown_signature)
    bm25_index._cache[999] = stale
    rebuilt = await get_index(db, 999)
    assert rebuilt is not stale
    assert rebuilt.signature == (0, 0)  # 该课程在测试库里没有分块


def test_local_store_reloads_after_other_process_writes(tmp_path):
    from app.rag.vector_store.base import VectorItem
    from app.rag.vector_store.local_store import LocalVectorStore

    path = tmp_path / "chunks.json"
    store = LocalVectorStore(path=path, collection="freshness")
    import asyncio

    async def _upsert() -> None:
        await store.upsert(
            [
                VectorItem(
                    chunk_id=1,
                    course_id=1,
                    document_id=1,
                    vector=[1.0, 0.0],
                    payload={"text": "首次写入"},
                )
            ]
        )

    asyncio.run(_upsert())
    assert set(store._load()) == {1}

    # 模拟 worker 进程写盘：直接改文件内容与 mtime
    payload = {
        "dim": 2,
        "items": {
            "1": {"course_id": 1, "document_id": 1, "vector": [1.0, 0.0], "payload": {}},
            "2": {"course_id": 1, "document_id": 2, "vector": [0.0, 1.0], "payload": {}},
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")

    # 同一个实例必须能读到新写入的 chunk
    assert set(store._load()) == {1, 2}
