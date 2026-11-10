from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.citation import SourceRefOut


class SaveAnswerRequest(BaseModel):
    """学生作答值：single=str，multiple=list[str]，judge=bool，short/essay=str。"""

    value: Any = None
    flagged: bool = False


class AnswerDraftOut(BaseModel):
    question_id: int
    seq: int
    type: str
    stem: str
    options: list[dict[str, Any]] | None = None
    score: float = 0
    value: Any = None
    flagged: bool = False


class AttemptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    paper_id: int
    student_id: int
    status: str
    total_score: float | None = None
    max_score: float | None = None
    started_at: datetime | None = None
    submitted_at: datetime | None = None
    graded_at: datetime | None = None
    paper_title: str | None = None
    duration_min: int = 60
    answers: list[AnswerDraftOut] = Field(default_factory=list)


class SubmitOut(BaseModel):
    attempt_id: int
    status: str
    job_id: str | None = None
    message: str = "已提交，正在阅卷"


class GradingStatusOut(BaseModel):
    attempt_id: int
    status: str
    graded: int = 0
    total: int = 0
    progress: int = 0
    job_id: str | None = None


class ReportItem(BaseModel):
    seq: int
    question_id: int
    type: str
    stem: str
    options: list[dict[str, Any]] | None = None
    student_answer: Any = None
    correct_answer: Any = None
    is_correct: bool | None = None
    score: float = 0
    max_score: float = 0
    rubric_detail: list[dict[str, Any]] = Field(default_factory=list)
    feedback: str | None = None
    error_tags: list[str] = Field(default_factory=list)
    needs_human: bool = False
    graded_by: str | None = None
    source_refs: list[SourceRefOut] = Field(default_factory=list)


class KPMastery(BaseModel):
    kp_id: int
    name: str
    total_score: float = 0
    earned_score: float = 0
    rate: float = 0
    question_count: int = 0
    wrong_count: int = 0


class AttemptReport(BaseModel):
    attempt_id: int
    paper_id: int
    course_id: int
    paper_title: str
    student_id: int
    status: str
    total_score: float = 0
    max_score: float = 0
    score_rate: float = 0
    duration_seconds: int | None = None
    items: list[ReportItem] = Field(default_factory=list)
    kp_mastery: list[KPMastery] = Field(default_factory=list)
    wrong_items: list[ReportItem] = Field(default_factory=list)
    error_tag_stats: dict[str, int] = Field(default_factory=dict)
    needs_human_count: int = 0
