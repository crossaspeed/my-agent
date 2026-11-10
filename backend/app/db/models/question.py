from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, SmallInteger, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import BigIntArray, BigIntPK, JSONDoc


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (Index("idx_questions_course_status", "course_id", "status"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    stem: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONDoc)
    answer: Mapped[Any] = mapped_column(JSONDoc, nullable=False)
    rubric: Mapped[list[dict[str, Any]]] = mapped_column(JSONDoc, nullable=False, default=list)
    explanation: Mapped[str | None] = mapped_column(Text)
    difficulty: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=3)
    source_refs: Mapped[list[dict[str, Any]]] = mapped_column(JSONDoc, nullable=False, default=list)
    kp_ids: Mapped[list[int]] = mapped_column(BigIntArray, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    quality: Mapped[dict[str, Any] | None] = mapped_column(JSONDoc)
    created_by: Mapped[int | None] = mapped_column(BigIntPK, ForeignKey("users.id"))
    reviewed_by: Mapped[int | None] = mapped_column(BigIntPK, ForeignKey("users.id"))
    review_note: Mapped[str | None] = mapped_column(Text)
    gen_meta: Mapped[dict[str, Any] | None] = mapped_column(JSONDoc)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now())
