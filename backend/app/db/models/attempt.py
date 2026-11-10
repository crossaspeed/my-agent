from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import BigIntPK, JSONDoc


class Attempt(Base):
    __tablename__ = "attempts"
    __table_args__ = (UniqueConstraint("paper_id", "student_id", name="uq_attempt_paper_student"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    paper_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    student_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("users.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="in_progress")
    total_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    max_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    graded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Answer(Base):
    __tablename__ = "answers"
    __table_args__ = (UniqueConstraint("attempt_id", "question_id", name="uq_answer_attempt_q"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    attempt_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("attempts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_id: Mapped[int] = mapped_column(BigIntPK, ForeignKey("questions.id"), nullable=False)
    student_answer: Mapped[Any] = mapped_column(JSONDoc)
    is_correct: Mapped[bool | None] = mapped_column(Boolean)
    score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    max_score: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, default=0)
    rubric_detail: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONDoc)
    feedback: Mapped[str | None] = mapped_column(Text)
    error_tags: Mapped[list[str] | None] = mapped_column(JSONDoc)
    graded_by: Mapped[str | None] = mapped_column(String(16))
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 2))
    needs_human: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    graded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now())
