"""课程级 BM25 索引（jieba 分词 + rank_bm25），惰性重建 + 进程内 LRU。"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any

import jieba
from rank_bm25 import BM25Okapi
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import DocumentChunk

logger = get_logger(__name__)

STOPWORDS = {
    "的", "了", "和", "与", "是", "在", "有", "为", "对", "中", "上", "下", "个", "这", "那",
    "等", "也", "就", "都", "而", "及", "或", "一个", "我们", "可以", "进行", "通过", "使用",
    "the", "a", "an", "of", "to", "and", "in", "is", "for", "on", "with", "as", "by",
}

_INDEX_TTL = 600
_MAX_COURSES = 3


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in jieba.lcut_for_search(text.lower()):
        token = raw.strip()
        if not token or token in STOPWORDS:
            continue
        if not any(ch.isalnum() or "\u4e00" <= ch <= "\u9fff" for ch in token):
            continue
        tokens.append(token)
    return tokens


class CourseBM25:
    """单门课程的 BM25 索引。"""

    def __init__(self, chunk_ids: list[int], corpus: list[list[str]]) -> None:
        self.chunk_ids = chunk_ids
        self.corpus = corpus
        self._bm25 = BM25Okapi(corpus) if corpus else None
        self.built_at = time.time()

    def search(self, query: str, top_k: int = 20) -> list[tuple[int, float]]:
        if self._bm25 is None:
            return []
        tokens = tokenize(query)
        if not tokens:
            return []
        scores = self._bm25.get_scores(tokens)
        order = sorted(range(len(scores)), key=lambda i: -scores[i])[:top_k]
        return [
            (self.chunk_ids[i], float(scores[i]))
            for i in order
            if scores[i] > 0
        ]


_cache: OrderedDict[int, CourseBM25] = OrderedDict()
_dirty: set[int] = set()
_lock = threading.RLock()


def invalidate(course_id: int | None = None) -> None:
    with _lock:
        if course_id is None:
            _dirty.update(_cache.keys())
            _cache.clear()
        else:
            _dirty.add(course_id)
            _cache.pop(course_id, None)


async def get_index(session: AsyncSession, course_id: int, force: bool = False) -> CourseBM25:
    with _lock:
        cached = _cache.get(course_id)
        if (
            cached
            and not force
            and course_id not in _dirty
            and time.time() - cached.built_at < _INDEX_TTL
        ):
            _cache.move_to_end(course_id)
            return cached

    rows = await session.execute(
        select(DocumentChunk.id, DocumentChunk.content).where(DocumentChunk.course_id == course_id)
    )
    chunk_ids: list[int] = []
    corpus: list[list[str]] = []
    for chunk_id, content in rows.all():
        chunk_ids.append(int(chunk_id))
        corpus.append(tokenize(content))

    index = CourseBM25(chunk_ids, corpus)
    with _lock:
        _cache[course_id] = index
        _cache.move_to_end(course_id)
        while len(_cache) > _MAX_COURSES:
            _cache.popitem(last=False)
        _dirty.discard(course_id)
    logger.info("bm25_built", course_id=course_id, chunks=len(chunk_ids))
    return index


def stats() -> dict[str, Any]:
    with _lock:
        return {"cached_courses": list(_cache.keys()), "dirty": sorted(_dirty)}
