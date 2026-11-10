from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.citation import SourceRefOut


class TutorSessionCreate(BaseModel):
    answer_id: int | None = None
    course_id: int | None = None
    question_id: int | None = None


class TutorMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: int
    role: str
    content: str
    refs: list[dict[str, Any]] = Field(default_factory=list)
    meta: dict[str, Any] | None = None
    created_at: datetime | None = None


class TutorSessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    student_id: int
    course_id: int
    answer_id: int | None = None
    question_id: int | None = None
    title: str | None = None
    summary: str | None = None
    created_at: datetime | None = None
    last_active_at: datetime | None = None
    message_count: int = 0
    last_message: str | None = None


class TutorSessionDetail(TutorSessionOut):
    messages: list[TutorMessageOut] = Field(default_factory=list)
    practice: list[dict[str, Any]] = Field(default_factory=list)


class TutorSendRequest(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


class TutorOpeningOut(BaseModel):
    session_id: int
    message: TutorMessageOut
    refs: list[SourceRefOut] = Field(default_factory=list)
    practice: list[dict[str, Any]] = Field(default_factory=list)
