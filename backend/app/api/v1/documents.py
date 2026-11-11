"""文档上传与知识库路由。"""

from __future__ import annotations

from fastapi import APIRouter, File, Query, UploadFile

from app.core.deps import CurrentUser, SessionDep
from app.rag.retriever import retrieve
from app.schemas.common import ok
from app.schemas.document import SearchRequest
from app.services import document_service
from app.services.access import require_course

router = APIRouter(tags=["文档与知识库"])


@router.post("/courses/{course_id}/documents", summary="上传课件（异步解析）")
async def upload(
    course_id: int,
    user: CurrentUser,
    session: SessionDep,
    file: UploadFile = File(..., description="PDF/PPTX/DOCX/MD/TXT，≤50MB"),
):
    content = await file.read()
    result = await document_service.upload_document(
        session, course_id, user, file.filename or "unnamed", content
    )
    return ok(result)


@router.get("/courses/{course_id}/documents", summary="文档列表")
async def list_documents(course_id: int, user: CurrentUser, session: SessionDep):
    return ok(await document_service.list_documents(session, course_id, user))


@router.get("/documents/{document_id}", summary="文档详情")
async def get_document(document_id: int, user: CurrentUser, session: SessionDep):
    return ok(await document_service.get_document(session, document_id, user))


@router.get("/documents/{document_id}/chunks", summary="分块列表（支持关键词与上下文）")
async def list_chunks(
    document_id: int,
    user: CurrentUser,
    session: SessionDep,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
    q: str | None = Query(default=None),
    around: int | None = Query(default=None, description="以某 chunk 为中心取上下文"),
):
    return ok(
        await document_service.list_chunks(
            session, document_id, user, page=page, size=size, q=q, around=around
        )
    )


@router.delete("/documents/{document_id}", summary="删除文档（级联清理 chunk 与向量）")
async def delete_document(document_id: int, user: CurrentUser, session: SessionDep):
    await document_service.delete_document(session, document_id, user)
    return ok(None, message="文档已删除")


@router.post("/documents/{document_id}/reparse", summary="重新解析")
async def reparse(document_id: int, user: CurrentUser, session: SessionDep):
    return ok(await document_service.reparse_document(session, document_id, user))


@router.post("/courses/{course_id}/search", summary="混合检索调试接口（论文实验用）")
async def search(
    course_id: int, req: SearchRequest, user: CurrentUser, session: SessionDep
):
    await require_course(session, course_id, user, "teacher")
    chunks = await retrieve(
        session,
        course_id,
        req.query,
        top_k=req.top_k,
        kp_ids=req.kp_ids,
        doc_ids=req.doc_ids,
        expand=req.expand,
        use_rerank=req.use_rerank,
        use_cache=False,
    )
    return ok(
        {
            "query": req.query,
            "count": len(chunks),
            "items": [c.to_dict() for c in chunks],
        }
    )
