"""Agent 状态定义（计划书 9.2，字段冻结）。"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict


class SourceRef(TypedDict, total=False):
    chunk_id: int
    document_id: int | None
    document_name: str | None
    page_no: int | None
    slide_no: int | None
    heading_path: str | None
    quote: str
    score: float


class DraftQuestion(TypedDict, total=False):
    type: Literal["single", "multiple", "judge", "short", "essay"]
    stem: str
    options: list[dict[str, Any]] | None
    answer: Any
    rubric: list[dict[str, Any]]
    explanation: str
    difficulty: int
    kp_ids: list[int]
    source_refs: list[SourceRef]


class QuestionGenState(TypedDict, total=False):
    # 输入
    course_id: int
    course_name: str
    kp_specs: list[dict[str, Any]]  # [{kp_id, name, count, difficulty, type}]
    requirements: str
    doc_ids: list[int] | None
    score_per_question: float
    # 中间态
    retrieval_map: dict[int, list[dict[str, Any]]]
    queries: dict[int, list[str]]
    drafts: Annotated[list[DraftQuestion], operator.add]
    invalid: list[dict[str, Any]]
    repair_round: int
    warnings: Annotated[list[str], operator.add]
    # 输出
    final_questions: list[DraftQuestion]
    dropped: list[dict[str, Any]]
    trace_id: str


class GraderState(TypedDict, total=False):
    course_id: int
    course_name: str
    question: dict[str, Any]
    student_answer: Any
    max_score: float
    retrieved_refs: list[dict[str, Any]]
    extracted_points: list[str]
    rubric_hits: list[dict[str, Any]]
    scores: Annotated[list[float], operator.add]
    score: float
    feedback: str
    error_tags: list[str]
    confidence: float
    needs_human: bool
    retry_count: int
    graded_by: str
    warnings: Annotated[list[str], operator.add]


class TutorState(TypedDict, total=False):
    session_id: int
    course_id: int
    course_name: str
    question: dict[str, Any]
    answer: dict[str, Any]
    grading: dict[str, Any]
    history: list[dict[str, Any]]
    user_query: str | None
    is_followup: bool
    diagnosis: str
    root_kp_id: int | None
    prerequisite_kps: list[int]
    refs: list[dict[str, Any]]
    explanation: str
    practice: list[dict[str, Any]]
    final_answer: str
    tokens: int
