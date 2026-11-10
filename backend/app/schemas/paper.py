from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.question import QuestionOut


class AutoPaperConfig(BaseModel):
    kp_ids: list[int] = Field(default_factory=list)
    types: dict[str, int] = Field(default_factory=lambda: {"single": 5})
    difficulty: dict[str, float] = Field(
        default_factory=lambda: {"easy": 0.2, "medium": 0.6, "hard": 0.2}
    )


class PaperCreate(BaseModel):
    course_id: int
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    mode: Literal["manual", "auto"] = "manual"
    question_ids: list[int] | None = None
    config: AutoPaperConfig | dict[str, Any] | None = None
    duration_min: int = Field(default=60, ge=5, le=300)
    total_score: float = Field(default=100, gt=0, le=1000)


class PaperQuestionOut(BaseModel):
    question_id: int
    seq: int
    score: float
    question: QuestionOut


class PaperOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    course_id: int
    creator_id: int
    title: str
    description: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    total_score: float = 100
    duration_min: int = 60
    status: str = "draft"
    start_at: datetime | None = None
    end_at: datetime | None = None
    created_at: datetime | None = None
    questions: list[PaperQuestionOut] = Field(default_factory=list)
    attempt_id: int | None = None
    attempt_status: str | None = None


class PaperListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    course_id: int
    title: str
    description: str | None = None
    total_score: float = 100
    duration_min: int = 60
    status: str = "draft"
    created_at: datetime | None = None
    question_count: int = 0
    attempt_id: int | None = None
    attempt_status: str | None = None
    my_score: float | None = None


class PaperStatsOut(BaseModel):
    paper_id: int
    title: str
    submitted: int
    avg_score: float
    max_score: float
    min_score: float
    items: list[dict[str, Any]] = Field(default_factory=list)
