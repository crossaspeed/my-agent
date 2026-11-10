"""SQLAlchemy 模型（一领域一文件，字段严格对齐计划书第 6 章）。"""

from app.db.models.attempt import Answer, Attempt
from app.db.models.course import Course, CourseMember
from app.db.models.document import Document, DocumentChunk
from app.db.models.job import Job
from app.db.models.knowledge import ChunkKnowledgePoint, KnowledgePoint
from app.db.models.llm_call import LLMCall
from app.db.models.paper import Paper, PaperQuestion
from app.db.models.question import Question
from app.db.models.tutor import TutorMessage, TutorSession
from app.db.models.user import User

__all__ = [
    "Answer",
    "Attempt",
    "ChunkKnowledgePoint",
    "Course",
    "CourseMember",
    "Document",
    "DocumentChunk",
    "Job",
    "KnowledgePoint",
    "LLMCall",
    "Paper",
    "PaperQuestion",
    "Question",
    "TutorMessage",
    "TutorSession",
    "User",
]
