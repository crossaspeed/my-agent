from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    course_id: int
    filename: str
    file_type: str
    size_bytes: int
    status: str
    error_msg: str | None = None
    page_count: int | None = None
    chunk_count: int = 0
    meta: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    job_id: str | None = None


class UploadResult(BaseModel):
    document_id: int
    job_id: str | None = None
    duplicated: bool = False
    message: str = "已开始解析"


class ChunkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    chunk_index: int
    content: str
    page_no: int | None = None
    slide_no: int | None = None
    heading_path: str | None = None
    token_count: int | None = None
    document_name: str | None = None


class ChunkListOut(BaseModel):
    items: list[ChunkOut]
    total: int
    page: int
    size: int
    highlight_id: int | None = None


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=6, ge=1, le=20)
    kp_ids: list[int] | None = None
    doc_ids: list[int] | None = None
    expand: bool = False


class RetrievedChunkOut(BaseModel):
    chunk_id: int
    content: str
    score: float
    source: str
    page_no: int | None = None
    heading_path: str | None = None
    document_id: int | None = None
    document_name: str | None = None
