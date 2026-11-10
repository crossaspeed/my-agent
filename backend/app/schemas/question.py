from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.citation import SourceRefOut

QuestionType = Literal["single", "multiple", "judge", "short", "essay"]


class GenerateRequest(BaseModel):
    course_id: int
    kp_ids: list[int] = Field(default_factory=list)
    types: dict[str, int] = Field(default_factory=lambda: {"single": 5})
    difficulty: dict[str, float] = Field(
        default_factory=lambda: {"easy": 0.2, "medium": 0.6, "hard": 0.2}
    )
    requirements: str = ""
    source_doc_ids: list[int] | None = None
    auto_publish: bool = False

    @field_validator("types")
    @classmethod
    def _check_types(cls, v: dict[str, int]) -> dict[str, int]:
        allowed = {"single", "multiple", "judge", "short", "essay"}
        unknown = set(v) - allowed
        if unknown:
            raise ValueError(f"不支持的题型：{unknown}")
        cleaned = {k: int(n) for k, n in v.items() if n and int(n) > 0}
        if not cleaned:
            raise ValueError("至少选择一种题型")
        return cleaned


class GenerateAccepted(BaseModel):
    job_id: str
    estimated_seconds: int = 40


class QuestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    course_id: int
    type: str
    stem: str
    options: list[dict[str, Any]] | None = None
    answer: Any = None
    rubric: list[dict[str, Any]] = Field(default_factory=list)
    explanation: str | None = None
    difficulty: int = 3
    source_refs: list[dict[str, Any]] = Field(default_factory=list)
    kp_ids: list[int] = Field(default_factory=list)
    status: str = "draft"
    quality: dict[str, Any] | None = None
    gen_meta: dict[str, Any] | None = None
    review_note: str | None = None
    created_at: datetime | None = None


class QuestionUpdate(BaseModel):
    stem: str | None = None
    options: list[dict[str, Any]] | None = None
    answer: Any = None
    rubric: list[dict[str, Any]] | None = None
    explanation: str | None = None
    difficulty: int | None = Field(default=None, ge=1, le=5)
    kp_ids: list[int] | None = None


class ReviewRequest(BaseModel):
    action: Literal["approve", "reject"]
    note: str | None = None


class BatchReviewRequest(BaseModel):
    ids: list[int] = Field(min_length=1)
    action: Literal["approve", "reject"]
    note: str | None = None


class QuestionPage(BaseModel):
    items: list[QuestionOut]
    total: int
    page: int
    size: int


class ReviewQueueOut(BaseModel):
    items: list[QuestionOut]
    total: int


class CitationVerifyResult(BaseModel):
    ok: bool
    reason: str | None = None
    refs: list[SourceRefOut] = Field(default_factory=list)
    fix_count: int = 0
    max_ratio: float = 0.0
