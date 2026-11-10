from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import BigIntPK


class KnowledgePoint(Base):
    __tablename__ = "knowledge_points"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_id: Mapped[int | None] = mapped_column(
        BigIntPK, ForeignKey("knowledge_points.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    importance: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=3)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ChunkKnowledgePoint(Base):
    __tablename__ = "chunk_knowledge_points"

    chunk_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("document_chunks.id", ondelete="CASCADE"), primary_key=True
    )
    kp_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("knowledge_points.id", ondelete="CASCADE"), primary_key=True
    )
