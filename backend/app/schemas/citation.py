from __future__ import annotations

from pydantic import BaseModel, Field


class SourceRefOut(BaseModel):
    """全系统统一的溯源结构（前端 CitationCard 消费）。"""

    chunk_id: int
    document_id: int | None = None
    document_name: str | None = None
    page_no: int | None = None
    slide_no: int | None = None
    heading_path: str | None = None
    quote: str = ""
    score: float = 0.0


class CitationQuality(BaseModel):
    citation_ok: bool = True
    citation_fix_count: int = 0
    quote_match_ratio: float = 1.0
    answer_supported: bool | None = None
    duplicated: bool = False
    warnings: list[str] = Field(default_factory=list)
