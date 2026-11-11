"""混合检索：向量 + BM25 + RRF 融合（计划书 8.5）。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import cache
from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import ChunkKnowledgePoint, Document, DocumentChunk
from app.rag import bm25_index
from app.rag.embedder import get_embedder
from app.rag.vector_store import get_vector_store

logger = get_logger(__name__)


@dataclass
class RetrievedChunk:
    chunk_id: int
    content: str
    score: float = 0.0
    relevance: float = 0.0
    source: str = "both"
    page_no: int | None = None
    slide_no: int | None = None
    heading_path: str | None = None
    document_id: int | None = None
    document_name: str | None = None
    document_deleted: bool = False
    # 查询词在该 chunk 中的覆盖率（0~1），用于判断"答非所问"
    coverage: float = 0.0
    # 查询有效词中不在本课程语料里的占比（0~1），用于判断"考纲外提问"
    unknown_ratio: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)

    def to_ref(self, quote: str | None = None) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "document_name": self.document_name,
            "page_no": self.page_no,
            "slide_no": self.slide_no,
            "heading_path": self.heading_path,
            "quote": (quote if quote is not None else self.content)[:400],
            "score": round(self.score, 4),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "content": self.content,
            "score": round(self.score, 4),
            "relevance": round(self.relevance, 4),
            "coverage": round(self.coverage, 4),
            "unknown_ratio": round(self.unknown_ratio, 4),
            "source": self.source,
            "page_no": self.page_no,
            "slide_no": self.slide_no,
            "heading_path": self.heading_path,
            "document_id": self.document_id,
            "document_name": self.document_name,
        }


def rrf_fuse(dense: list[int], sparse: list[int], k: int = 60) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion：只依赖排名，无需调权重。"""
    scores: dict[int, float] = {}
    for rank, cid in enumerate(dense, start=1):
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
    for rank, cid in enumerate(sparse, start=1):
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: -kv[1])


def _cache_key(course_id: int, query: str, top_k: int, kp_ids: list[int] | None,
               doc_ids: list[int] | None) -> str:
    raw = json.dumps([course_id, query, top_k, kp_ids, doc_ids], ensure_ascii=False)
    return "search:" + hashlib.sha256(raw.encode()).hexdigest()[:32]


async def _fetch_chunks(session: AsyncSession, chunk_ids: list[int]) -> dict[int, RetrievedChunk]:
    if not chunk_ids:
        return {}
    rows = await session.execute(
        select(DocumentChunk, Document.filename, Document.status)
        .join(Document, Document.id == DocumentChunk.document_id, isouter=True)
        .where(DocumentChunk.id.in_(chunk_ids))
    )
    out: dict[int, RetrievedChunk] = {}
    for chunk, filename, doc_status in rows.all():
        out[chunk.id] = RetrievedChunk(
            chunk_id=chunk.id,
            content=chunk.content,
            page_no=chunk.page_no,
            slide_no=chunk.slide_no,
            heading_path=chunk.heading_path,
            document_id=chunk.document_id,
            document_name=filename,
            document_deleted=filename is None or doc_status == "deleted",
        )
    return out


async def _filter_by_kp(
    session: AsyncSession, chunk_ids: list[int], kp_ids: list[int]
) -> set[int]:
    if not kp_ids:
        return set(chunk_ids)
    rows = await session.execute(
        select(ChunkKnowledgePoint.chunk_id).where(
            ChunkKnowledgePoint.chunk_id.in_(chunk_ids),
            ChunkKnowledgePoint.kp_id.in_(kp_ids),
        )
    )
    return {int(r[0]) for r in rows.all()}


async def retrieve(
    session: AsyncSession,
    course_id: int,
    query: str,
    top_k: int | None = None,
    kp_ids: list[int] | None = None,
    doc_ids: list[int] | None = None,
    use_rerank: bool = False,
    expand: bool = False,
    use_cache: bool = True,
) -> list[RetrievedChunk]:
    """混合检索入口（签名与计划书 8.5 冻结版本一致）。"""
    top_k = top_k or settings.RETRIEVE_TOP_K
    key = _cache_key(course_id, query, top_k, kp_ids, doc_ids)
    if use_cache:
        cached = cache.get_json(key)
        if cached:
            return [RetrievedChunk(**item) for item in cached]

    candidates = settings.RETRIEVE_CANDIDATES
    embedder = get_embedder()
    vector = await embedder.embed_query(query)
    dense_hits = await get_vector_store().search(
        course_id, vector, top_k=candidates, doc_ids=doc_ids
    )
    dense_ids = [hit.chunk_id for hit in dense_hits]
    dense_score = {hit.chunk_id: max(0.0, hit.score) for hit in dense_hits}

    index = await bm25_index.get_index(session, course_id)
    sparse_hits = index.search(query, top_k=candidates)
    sparse_ids = [cid for cid, score in sparse_hits if score > 0]
    # BM25 原始分没有上界。早期实现用「分数 / 本次最高分」归一，导致 top1 恒等于 1.0，
    # relevance 因此失去绝对尺度，MIN_RETRIEVE_SCORE 实际永不触发。
    # 改为饱和变换 raw/(raw+K)：单调有界，同时保留"这条命中到底有多强"的绝对信息。
    sparse_norm: dict[int, float] = {
        cid: score / (score + settings.BM25_SATURATION_K)
        for cid, score in sparse_hits
        if score > 0
    }

    # 查询词级信号：哪些词根本不在本课程语料里（考纲外判定），以及 top chunk 覆盖了几个词
    terms = bm25_index.tokenize(query)
    known_terms = [t for t in terms if t in index.vocab]
    unknown_ratio = 1.0 - (len(known_terms) / len(terms)) if terms else 1.0

    if not dense_ids and not sparse_ids:
        return []

    fused = rrf_fuse(dense_ids, sparse_ids, settings.RRF_K)
    fused_ids = [cid for cid, _ in fused][: max(top_k * 3, 20)]
    if kp_ids:
        allowed = await _filter_by_kp(session, fused_ids, kp_ids)
        fused_ids = [cid for cid in fused_ids if cid in allowed]

    chunk_map = await _fetch_chunks(session, fused_ids)
    max_rrf = max((score for _, score in fused), default=1.0) or 1.0
    rrf_map = dict(fused)

    results: list[RetrievedChunk] = []
    for cid in fused_ids:
        chunk = chunk_map.get(cid)
        if chunk is None:
            continue
        dense_set = cid in dense_score
        sparse_set = cid in sparse_norm
        chunk.source = "both" if dense_set and sparse_set else ("dense" if dense_set else "sparse")
        chunk.score = round(rrf_map.get(cid, 0.0) / max_rrf, 4)
        chunk.coverage = round(index.coverage(terms, cid), 4)
        chunk.unknown_ratio = round(unknown_ratio, 4)
        # 三路信号取最大：向量语义分、BM25 饱和分、查询词覆盖率。
        # 覆盖率是纯词面量纲（0~1），能兜住"BM25 分数被饱和压缩到阈值以下"的误拒。
        chunk.relevance = round(
            max(dense_score.get(cid, 0.0), sparse_norm.get(cid, 0.0), chunk.coverage), 4
        )
        results.append(chunk)

    if expand and results:
        results = await _expand(session, results, top_k)

    results = results[:top_k]
    if use_cache and results:
        cache.set_json(key, [r.to_dict() for r in results], settings.CACHE_TTL_SEARCH)
    logger.info("retrieve", course_id=course_id, query=query[:40], hits=len(results))
    return results


async def _expand(
    session: AsyncSession, results: list[RetrievedChunk], top_k: int
) -> list[RetrievedChunk]:
    """上下文扩展：命中 chunk 追加前后各一个同级 chunk。"""
    already = {r.chunk_id for r in results}
    extra: list[RetrievedChunk] = []
    for item in results[: max(1, top_k // 2)]:
        if item.document_id is None:
            continue
        rows = await session.execute(
            select(DocumentChunk)
            .where(
                DocumentChunk.document_id == item.document_id,
                DocumentChunk.chunk_index >= (item.meta.get("chunk_index", 0) or 0) - 1,
            )
            .order_by(DocumentChunk.chunk_index)
            .limit(3)
        )
        for chunk in rows.scalars().all():
            if chunk.id in already:
                continue
            already.add(chunk.id)
            extra.append(
                RetrievedChunk(
                    chunk_id=chunk.id,
                    content=chunk.content,
                    score=item.score * 0.5,
                    relevance=item.relevance * 0.5,
                    source="expand",
                    page_no=chunk.page_no,
                    heading_path=chunk.heading_path,
                    document_id=chunk.document_id,
                    document_name=item.document_name,
                )
            )
    return results + extra
