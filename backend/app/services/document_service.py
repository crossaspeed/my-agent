"""文档服务：上传校验 → 去重 → 落盘 → 异步解析入库 → 分块查询。"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import cache
from app.core.config import settings
from app.core.exceptions import BadRequest, Conflict, NotFound, ParseFailed
from app.core.logging import get_logger
from app.db.base import task_session
from app.db.models import (
    ChunkKnowledgePoint,
    Document,
    DocumentChunk,
    Job,
    KnowledgePoint,
    User,
)
from app.rag import bm25_index
from app.rag.chunker import ChunkConfig, chunk_segments, chunk_stats
from app.rag.cleaner import clean_segments
from app.rag.embedder import get_embedder
from app.rag.parsers import SUPPORTED_TYPES, parse_file
from app.rag.vector_store import get_vector_store
from app.rag.vector_store.base import VectorItem
from app.schemas.document import ChunkListOut, ChunkOut, DocumentOut, UploadResult
from app.services import job_service
from app.services.access import require_course
from app.workers.registry import register
from app.workers.runner import submit

logger = get_logger(__name__)

ALLOWED_EXT = SUPPORTED_TYPES
EXT_ALIAS = {"jpeg": "jpg"}


def _ext_of(filename: str) -> str:
    return Path(filename).suffix.lower().lstrip(".")


def sniff_file_type(content: bytes, ext: str) -> str:
    """真实类型校验（不依赖 libmagic，Windows 友好）。"""
    head = content[:8]
    if ext == "pdf":
        if not content.startswith(b"%PDF"):
            raise BadRequest("文件内容不是有效的 PDF")
        return "pdf"
    if ext in ("pptx", "docx"):
        if not head.startswith(b"PK"):
            raise BadRequest(f"文件内容不是有效的 {ext.upper()}（应为 zip 容器）")
        return ext
    if ext in ("ppt", "doc"):
        if not head.startswith(b"\xd0\xcf\x11\xe0"):
            raise BadRequest(f"文件内容不是有效的 {ext.upper()}")
        return ext
    if ext in ("md", "markdown", "txt"):
        try:
            content.decode("utf-8")
        except UnicodeDecodeError:
            try:
                content.decode("gb18030")
            except UnicodeDecodeError as exc:
                raise BadRequest("文本文件编码无法识别（支持 UTF-8 / GB18030）") from exc
        return ext
    raise BadRequest(f"不支持的文件类型：{ext}")


async def upload_document(
    session: AsyncSession,
    course_id: int,
    user: User,
    filename: str,
    content: bytes,
    enqueue: bool = True,
) -> UploadResult:
    course, _ = await require_course(session, course_id, user, "teacher")
    ext = _ext_of(filename)
    if ext not in ALLOWED_EXT:
        raise BadRequest(f"仅支持 {', '.join(sorted(ALLOWED_EXT))} 格式")
    if not content:
        raise BadRequest("文件内容为空（0 字节）")
    if len(content) > settings.max_upload_bytes:
        raise BadRequest(f"文件超过 {settings.MAX_UPLOAD_MB}MB 限制")
    file_type = sniff_file_type(content, ext)
    content_hash = hashlib.sha256(content).hexdigest()

    existing = await session.execute(
        select(Document).where(
            Document.course_id == course_id, Document.content_hash == content_hash
        )
    )
    dup = existing.scalar_one_or_none()
    if dup is not None and dup.status != "deleted":
        job = await job_service.find_by_target(session, "parse_document", dup.id)
        if dup.status == "ready":
            return UploadResult(
                document_id=dup.id, job_id=None, duplicated=True,
                message="相同文件已存在，已直接复用（无需重复解析）",
            )
        if dup.status in ("pending", "parsing", "chunking", "embedding") and job:
            return UploadResult(
                document_id=dup.id, job_id=job.task_id, duplicated=True, message="文件正在解析中"
            )

    upload_dir = settings.resolve_path(settings.UPLOAD_DIR) / str(course_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    stored = upload_dir / f"{uuid.uuid4().hex}.{ext}"
    stored.write_bytes(content)

    doc = dup or Document(course_id=course_id, content_hash=content_hash, uploader_id=user.id)
    doc.filename = filename[:255]
    doc.stored_path = str(stored)
    doc.file_type = file_type
    doc.size_bytes = len(content)
    doc.status = "pending"
    doc.error_msg = None
    doc.meta = {}
    session.add(doc)
    await session.flush()

    job = await job_service.create(
        session,
        job_type="parse_document",
        target_id=doc.id,
        course_id=course_id,
        created_by=user.id,
        payload={"document_id": doc.id},
    )
    await session.commit()
    if enqueue:
        submit("parse_document", job.task_id, {"document_id": doc.id, "course_id": course_id,
                                               "task_id": job.task_id})
    logger.info("document_uploaded", document_id=doc.id, size=len(content), course_id=course_id)
    assert course is not None
    return UploadResult(document_id=doc.id, job_id=job.task_id, message="已开始解析")


async def list_documents(session: AsyncSession, course_id: int, user: User) -> list[DocumentOut]:
    await require_course(session, course_id, user, "member")
    rows = await session.execute(
        select(Document)
        .where(Document.course_id == course_id, Document.status != "deleted")
        .order_by(Document.created_at.desc())
    )
    docs = list(rows.scalars().all())
    jobs = {}
    if docs:
        job_rows = await session.execute(
            select(Job).where(
                Job.job_type == "parse_document",
                Job.target_id.in_([d.id for d in docs]),
            ).order_by(Job.created_at.desc())
        )
        for job in job_rows.scalars().all():
            jobs.setdefault(job.target_id, job.task_id)
    out = []
    for doc in docs:
        item = DocumentOut.model_validate(doc)
        out.append(item.model_copy(update={"job_id": jobs.get(doc.id)}))
    return out


async def get_document(session: AsyncSession, document_id: int, user: User) -> DocumentOut:
    doc = await session.get(Document, document_id)
    if doc is None or doc.status == "deleted":
        raise NotFound("文档不存在")
    await require_course(session, doc.course_id, user, "member")
    job = await job_service.find_by_target(session, "parse_document", doc.id)
    return DocumentOut.model_validate(doc).model_copy(
        update={"job_id": job.task_id if job else None}
    )


async def list_chunks(
    session: AsyncSession,
    document_id: int,
    user: User,
    page: int = 1,
    size: int = 20,
    q: str | None = None,
    around: int | None = None,
) -> ChunkListOut:
    doc = await session.get(Document, document_id)
    if doc is None:
        raise NotFound("文档不存在")
    await require_course(session, doc.course_id, user, "member")

    base = select(DocumentChunk).where(DocumentChunk.document_id == document_id)
    count_stmt = select(func.count()).select_from(DocumentChunk).where(
        DocumentChunk.document_id == document_id
    )
    if q:
        base = base.where(DocumentChunk.content.contains(q))
        count_stmt = count_stmt.where(DocumentChunk.content.contains(q))

    highlight = None
    if around:
        anchor = await session.get(DocumentChunk, around)
        if anchor is not None and anchor.document_id == document_id:
            highlight = anchor.id
            base = base.where(
                DocumentChunk.chunk_index >= anchor.chunk_index - 1,
                DocumentChunk.chunk_index <= anchor.chunk_index + 1,
            )
            count_stmt = count_stmt.where(
                DocumentChunk.chunk_index >= anchor.chunk_index - 1,
                DocumentChunk.chunk_index <= anchor.chunk_index + 1,
            )
            page = 1

    total = int(await session.scalar(count_stmt) or 0)
    rows = await session.execute(
        base.order_by(DocumentChunk.chunk_index).offset((page - 1) * size).limit(size)
    )
    items = [
        ChunkOut.model_validate(chunk).model_copy(update={"document_name": doc.filename})
        for chunk in rows.scalars().all()
    ]
    return ChunkListOut(items=items, total=total, page=page, size=size, highlight_id=highlight)


async def delete_document(session: AsyncSession, document_id: int, user: User) -> None:
    doc = await session.get(Document, document_id)
    if doc is None or doc.status == "deleted":
        raise NotFound("文档不存在")
    await require_course(session, doc.course_id, user, "owner")

    # 软删：保留题目溯源（前端灰显「原文已删除」），物理清理 chunk 与向量
    await get_vector_store().delete_by_doc(document_id)
    chunks = await session.execute(
        select(DocumentChunk.id).where(DocumentChunk.document_id == document_id)
    )
    chunk_ids = [int(r[0]) for r in chunks.all()]
    if chunk_ids:
        await session.execute(
            ChunkKnowledgePoint.__table__.delete().where(
                ChunkKnowledgePoint.chunk_id.in_(chunk_ids)
            )
        )
    await session.execute(
        DocumentChunk.__table__.delete().where(DocumentChunk.document_id == document_id)
    )
    doc.status = "deleted"
    doc.chunk_count = 0
    session.add(doc)
    bm25_index.invalidate(doc.course_id)
    cache.delete_prefix("search:")
    logger.info("document_deleted", document_id=document_id, chunks=len(chunk_ids))


async def reparse_document(session: AsyncSession, document_id: int, user: User) -> UploadResult:
    doc = await session.get(Document, document_id)
    if doc is None:
        raise NotFound("文档不存在")
    await require_course(session, doc.course_id, user, "owner")
    if not Path(doc.stored_path).exists():
        raise Conflict("源文件已丢失，请重新上传")
    doc.status = "pending"
    doc.error_msg = None
    session.add(doc)
    job = await job_service.create(
        session,
        job_type="parse_document",
        target_id=doc.id,
        course_id=doc.course_id,
        created_by=user.id,
        payload={"document_id": doc.id},
    )
    await session.commit()
    submit("parse_document", job.task_id, {"document_id": doc.id, "course_id": doc.course_id,
                                           "task_id": job.task_id})
    return UploadResult(document_id=doc.id, job_id=job.task_id, message="已重新提交解析")


# ---------------- 后台任务 ----------------
@register("parse_document")
async def parse_document_task(payload: dict[str, Any]) -> None:
    task_id = payload["task_id"]
    document_id = int(payload["document_id"])
    async with task_session() as session:
        try:
            await _run_parse(session, task_id, document_id)
        except Exception as exc:  # 失败必须落库
            logger.exception("parse_failed", document_id=document_id, error=str(exc))
            doc = await session.get(Document, document_id)
            if doc is not None:
                doc.status = "failed"
                doc.error_msg = str(exc)[:2000]
                session.add(doc)
            await job_service.fail(session, task_id, str(exc))
            await session.commit()


async def _run_parse(session: AsyncSession, task_id: str, document_id: int) -> None:
    doc = await session.get(Document, document_id)
    if doc is None:
        raise NotFound("文档不存在")

    await job_service.update(session, task_id, status="running", progress=5, stage="解析中")
    doc.status = "parsing"
    session.add(doc)
    await session.commit()

    parse_result = await _parse_async(Path(doc.stored_path), doc.file_type)

    await job_service.update(session, task_id, progress=40, stage="清洗分块")
    cleaned, clean_stats = clean_segments(parse_result.segments)
    if not cleaned:
        raise ParseFailed("清洗后无有效文本（可能是纯图片或空文档）")
    chunks = chunk_segments(cleaned, ChunkConfig())
    if not chunks:
        raise ParseFailed("未提取到有效文本")

    await job_service.update(session, task_id, progress=60, stage="写入知识库")
    # 幂等：先清理旧数据，避免重跑产生重复
    await get_vector_store().delete_by_doc(document_id)
    old_ids = await session.execute(
        select(DocumentChunk.id).where(DocumentChunk.document_id == document_id)
    )
    old = [int(r[0]) for r in old_ids.all()]
    if old:
        await session.execute(
            ChunkKnowledgePoint.__table__.delete().where(ChunkKnowledgePoint.chunk_id.in_(old))
        )
        await session.execute(
            DocumentChunk.__table__.delete().where(DocumentChunk.document_id == document_id)
        )
        await session.flush()

    doc.status = "chunking"
    rows: list[DocumentChunk] = []
    for idx, chunk in enumerate(chunks):
        row = DocumentChunk(
            document_id=document_id,
            course_id=doc.course_id,
            chunk_index=idx,
            content=chunk.content,
            token_count=chunk.token_count,
            page_no=chunk.page_no,
            slide_no=chunk.slide_no,
            heading_path=chunk.heading_path,
            char_start=chunk.char_start,
            char_end=chunk.char_end,
            meta=chunk.meta,
        )
        session.add(row)
        rows.append(row)
    await session.flush()

    await job_service.update(session, task_id, progress=75, stage="向量化")
    doc.status = "embedding"
    session.add(doc)
    await session.commit()

    embedder = get_embedder()
    store = get_vector_store()
    batch_size = settings.EMBEDDING_BATCH_SIZE
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        vectors = await embedder.embed_documents([r.content for r in batch])
        await store.upsert(
            [
                VectorItem(
                    chunk_id=row.id,
                    course_id=doc.course_id,
                    document_id=document_id,
                    vector=vector,
                    payload={"page_no": row.page_no or 0, "heading_path": row.heading_path or ""},
                )
                for row, vector in zip(batch, vectors, strict=False)
            ]
        )
        progress = 75 + int(15 * min(1.0, (start + batch_size) / len(rows)))
        await job_service.update(session, task_id, progress=min(progress, 93), stage="向量化")

    await job_service.update(session, task_id, progress=95, stage="建立检索索引")
    tagged = await tag_chunks_to_kps(session, doc.course_id, [r.id for r in rows])
    bm25_index.invalidate(doc.course_id)
    cache.delete_prefix("search:")

    stats = chunk_stats(chunks)
    doc.status = "ready"
    doc.page_count = parse_result.page_count
    doc.chunk_count = len(rows)
    doc.meta = {
        **(parse_result.meta or {}),
        "clean_stats": clean_stats.to_dict(),
        "chunk_stats": stats,
        "tagged_kp_links": tagged,
    }
    session.add(doc)
    await job_service.success(
        session,
        task_id,
        result={
            "document_id": document_id,
            "chunk_count": len(rows),
            "page_count": parse_result.page_count,
            "clean_ratio": clean_stats.clean_ratio,
            "chunk_stats": stats,
        },
    )
    await session.commit()
    logger.info("parse_success", document_id=document_id, chunks=len(rows))


async def process_document_now(session: AsyncSession, document_id: int) -> None:
    """同步执行解析（CLI / 测试用，不经过队列）。"""
    job = await job_service.create(
        session, "parse_document", target_id=document_id, payload={"document_id": document_id}
    )
    await session.commit()
    await _run_parse(session, job.task_id, document_id)


async def _parse_async(path: Path, file_type: str) -> Any:
    import asyncio

    return await asyncio.to_thread(parse_file, path, file_type)


async def tag_chunks_to_kps(
    session: AsyncSession, course_id: int, chunk_ids: list[int]
) -> int:
    """把分块挂到知识点（供按知识点检索与出题过滤使用）。"""
    if not chunk_ids:
        return 0
    kps = list(
        (
            await session.execute(
                select(KnowledgePoint).where(KnowledgePoint.course_id == course_id)
            )
        )
        .scalars()
        .all()
    )
    if not kps:
        return 0
    chunks = list(
        (
            await session.execute(
                select(DocumentChunk).where(DocumentChunk.id.in_(chunk_ids))
            )
        )
        .scalars()
        .all()
    )
    # 幂等：先清掉这些分块的旧关联，避免重复插入
    await session.execute(
        ChunkKnowledgePoint.__table__.delete().where(
            ChunkKnowledgePoint.chunk_id.in_([c.id for c in chunks] or [0])
        )
    )
    links = 0
    for chunk in chunks:
        content = chunk.content
        heading = chunk.heading_path or ""
        scored: list[tuple[float, int]] = []
        for kp in kps:
            score = 0.0
            if kp.name and kp.name in heading:
                score += 3.0
            if kp.name and kp.name in content:
                score += 2.0
            score += content.count(kp.name) * 0.5 if kp.name else 0
            if score > 0:
                scored.append((score, kp.id))
        scored.sort(reverse=True)
        for _score, kp_id in scored[:2]:
            session.add(ChunkKnowledgePoint(chunk_id=chunk.id, kp_id=kp_id))
            links += 1
    await session.flush()
    return links


_STUCK_PENDING_SECONDS = 120
_STUCK_RUNNING_SECONDS = 180
_MAX_PARSE_ATTEMPTS = 3


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _stuck_reason(job: Job | None, now: datetime) -> str | None:
    """判断解析任务是否已经卡住；返回 None 表示仍在正常运行。"""
    if job is None:
        return "missing"
    if job.status == "failed":
        return "failed"
    if job.status == "success":
        return "success_but_not_ready"
    if job.status == "pending":
        created = _aware(job.created_at)
        if created and (now - created).total_seconds() > _STUCK_PENDING_SECONDS:
            return "pending_timeout"
        return None
    if job.status == "running":
        beat = _aware(job.heartbeat_at) or _aware(job.started_at) or _aware(job.created_at)
        if beat and (now - beat).total_seconds() > _STUCK_RUNNING_SECONDS:
            return "heartbeat_timeout"
    return None


async def reconcile_stuck_documents(session: AsyncSession, *, enqueue: bool = True) -> int:
    """启动时回收卡住的解析任务（前端不会无限转圈）。

    消息可能因为 worker 未注册任务、Redis 重启、进程被杀而丢失，此时 Job 永远停在
    pending、文档永远停在 pending/parsing。这里按明确规则兜底：
      - 任务缺失 / pending 超时 / running 心跳超时 / 已完成但文档未就绪 → 重新入队
      - 任务已 failed → 文档标记失败并带出原因
      - 同一文档累计尝试超过 _MAX_PARSE_ATTEMPTS → 标记失败，交给用户手动重试
    """
    rows = await session.execute(
        select(Document).where(
            Document.status.in_(["pending", "parsing", "chunking", "embedding"])
        )
    )
    docs = list(rows.scalars().all())
    if not docs:
        return 0

    now = datetime.now(UTC)
    handled = 0
    submits: list[tuple[str, dict[str, Any]]] = []

    for doc in docs:
        job = await job_service.find_by_target(session, "parse_document", doc.id)
        attempts = (
            await session.scalar(
                select(func.count())
                .select_from(Job)
                .where(Job.job_type == "parse_document", Job.target_id == doc.id)
            )
        ) or 0

        reason = _stuck_reason(job, now)
        if reason is None:
            continue

        if reason == "failed" or not enqueue or attempts >= _MAX_PARSE_ATTEMPTS:
            doc.status = "failed"
            doc.error_msg = (
                (job.error_msg if job and job.error_msg else None)
                or "解析任务长时间无进展（可能因服务重启丢失），请点击重新解析"
            )[:500]
            session.add(doc)
            handled += 1
            continue

        if job is not None:
            await job_service.fail(session, job.task_id, f"任务卡住（{reason}），已自动重新入队")
        new_job = await job_service.create(
            session,
            job_type="parse_document",
            target_id=doc.id,
            course_id=doc.course_id,
            created_by=doc.uploader_id,
            payload={"document_id": doc.id},
        )
        doc.status = "pending"
        doc.error_msg = None
        session.add(doc)
        submits.append(
            (
                new_job.task_id,
                {"document_id": doc.id, "course_id": doc.course_id, "task_id": new_job.task_id},
            )
        )
        handled += 1
        logger.warning(
            "document_requeued", document_id=doc.id, reason=reason, attempts=attempts + 1
        )

    await session.commit()
    # 先落库再投递：worker 拿到消息时必须能查到 job 行
    for task_id, payload in submits:
        submit("parse_document", task_id, payload)
    return handled
