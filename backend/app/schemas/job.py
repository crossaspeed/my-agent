from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    task_id: str
    job_type: str
    target_id: int | None = None
    course_id: int | None = None
    status: str
    progress: int = 0
    stage: str | None = None
    result: dict[str, Any] | None = None
    error_msg: str | None = None
    created_at: datetime | None = None
    finished_at: datetime | None = None


class HealthOut(BaseModel):
    status: str
    app_env: str
    version: str
    dependencies: dict[str, Any] = Field(default_factory=dict)


class LLMStatsOut(BaseModel):
    total_calls: int = 0
    success_rate: float = 0
    avg_latency_ms: float = 0
    total_tokens: int = 0
    by_scene: list[dict[str, Any]] = Field(default_factory=list)
    by_day: list[dict[str, Any]] = Field(default_factory=list)


class ReindexRequest(BaseModel):
    course_id: int | None = None


class OverviewOut(BaseModel):
    documents: int = 0
    chunks: int = 0
    questions: int = 0
    published_questions: int = 0
    papers: int = 0
    students: int = 0
    attempts: int = 0
    active_students_7d: int = 0
    avg_score: float = 0
    knowledge_points: int = 0
    recent_jobs: list[dict[str, Any]] = Field(default_factory=list)
