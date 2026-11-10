from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CourseCreate(BaseModel):
    code: str = Field(min_length=2, max_length=32)
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None
    settings: dict[str, Any] = Field(default_factory=dict)


class CourseUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    description: str | None = None
    settings: dict[str, Any] | None = None


class CourseStats(BaseModel):
    documents: int = 0
    questions: int = 0
    papers: int = 0
    students: int = 0
    knowledge_points: int = 0
    chunks: int = 0


class CourseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    description: str | None = None
    owner_id: int
    settings: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    my_role: str = "student"
    stats: CourseStats = Field(default_factory=CourseStats)


class MemberAddRequest(BaseModel):
    usernames: list[str] = Field(min_length=1, max_length=200)


class MemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    username: str
    real_name: str | None = None
    role: str


class KnowledgePointCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    parent_id: int | None = None
    description: str | None = None
    importance: int = Field(default=3, ge=1, le=5)
    sort_order: int = 0


class KnowledgePointUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    description: str | None = None
    importance: int | None = Field(default=None, ge=1, le=5)
    sort_order: int | None = None
    parent_id: int | None = None


class KnowledgePointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    course_id: int
    parent_id: int | None = None
    name: str
    description: str | None = None
    importance: int = 3
    sort_order: int = 0
    children: list[KnowledgePointOut] = Field(default_factory=list)
    chunk_count: int = 0


KnowledgePointOut.model_rebuild()


class KnowledgePointAutoRequest(BaseModel):
    """从知识库自动抽取知识点树（P1，当前用 LLM/启发式实现）。"""

    max_points: int = Field(default=12, ge=3, le=30)
    doc_ids: list[int] | None = None
