"""课程级 BM25 索引（jieba 分词 + rank_bm25），惰性重建 + 进程内 LRU。"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any

import jieba
from rank_bm25 import BM25Okapi
from sqlalchemy import func, select
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

    def __init__(
        self,
        chunk_ids: list[int],
        corpus: list[list[str]],
        signature: tuple[int, int] | None = None,
    ) -> None:
        self.chunk_ids = chunk_ids
        self.corpus = corpus
        # (分块数, 最大分块 id)：用于跨进程感知语料变化（解析任务在别的进程写库）
        self.signature = signature
        self._bm25 = BM25Okapi(corpus) if corpus else None
        self.built_at = time.time()
        self._token_sets: dict[int, set[str]] | None = None
        self._vocab: set[str] | None = None

    @property
    def token_sets(self) -> dict[int, set[str]]:
        """chunk_id → 词集合，用于计算查询词覆盖情况（惰性构建）。"""
        if self._token_sets is None:
            self._token_sets = {
                cid: set(tokens) for cid, tokens in zip(self.chunk_ids, self.corpus, strict=False)
            }
        return self._token_sets

    @property
    def vocab(self) -> set[str]:
        """本课程语料的全部词项，用于判断查询词是否"考纲外"（惰性构建）。"""
        if self._vocab is None:
            vocab: set[str] = set()
            for tokens in self.corpus:
                vocab.update(tokens)
            self._vocab = vocab
        return self._vocab

    def coverage(self, terms: list[str], chunk_id: int) -> float:
        """查询词在该 chunk 中的覆盖率（0~1）：衡量"检索到的片段到底讲了多少我问的东西"。"""
        if not terms:
            return 0.0
        tokens = self.token_sets.get(chunk_id)
        if not tokens:
            return 0.0
        hit = sum(1 for term in terms if term in tokens)
        return hit / len(terms)

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


async def _corpus_signature(session: AsyncSession, course_id: int) -> tuple[int, int]:
    row = (
        await session.execute(
            select(func.count(DocumentChunk.id), func.max(DocumentChunk.id)).where(
                DocumentChunk.course_id == course_id
            )
        )
    ).one()
    return int(row[0] or 0), int(row[1] or 0)


async def get_index(session: AsyncSession, course_id: int, force: bool = False) -> CourseBM25:
    with _lock:
        cached = _cache.get(course_id)
    # 缓存命中还要校验语料签名：课件由 worker 进程解析入库，API 进程的索引若不校验
    # 会一直用旧语料，表现为"刚上传的课件搜不到"（最多滞后 _INDEX_TTL 秒）
    if (
        cached
        and not force
        and course_id not in _dirty
        and time.time() - cached.built_at < _INDEX_TTL
        and cached.signature == await _corpus_signature(session, course_id)
    ):
        with _lock:
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

    index = CourseBM25(chunk_ids, corpus, signature=(len(chunk_ids), max(chunk_ids, default=0)))
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
