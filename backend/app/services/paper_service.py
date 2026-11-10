"""试卷服务：手动/自动组卷、发布、学生端答案剥离。"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequest, Conflict, NotFound
from app.db.models import Attempt, Paper, PaperQuestion, Question, User
from app.schemas.paper import (
    AutoPaperConfig,
    PaperCreate,
    PaperListItem,
    PaperOut,
    PaperQuestionOut,
)
from app.services.access import get_course_role, require_course
from app.services.question_service import question_to_out

DIFFICULTY_WEIGHT = {"easy": 2, "medium": 3, "hard": 5}
TYPE_BASE_SCORE = {"single": 1.0, "multiple": 1.5, "judge": 1.0, "short": 2.5, "essay": 3.0}


def _match_difficulty(question_difficulty: int, dist: dict[str, float]) -> float:
    """难度匹配度：与目标难度分布越接近分越高。"""
    total = sum(max(0.0, v) for v in dist.values()) or 1.0
    weight = 0.0
    for key, ratio in dist.items():
        weight += max(0.0, ratio) / total * (1.0 - abs(DIFFICULTY_WEIGHT.get(key, 3) - question_difficulty) / 4.0)
    return weight


def _assign_scores(questions: list[Question], total_score: float) -> list[float]:
    """按题型基准分归一化到总分，四舍五入到 0.5 分档，并修正尾差。"""
    bases = [TYPE_BASE_SCORE.get(q.type, 1.0) for q in questions]
    base_sum = sum(bases) or 1.0
    raw = [total_score * b / base_sum for b in bases]
    scores = [round(r * 2) / 2 for r in raw]
    diff = round(total_score - sum(scores), 1)
    if abs(diff) >= 0.5 and scores:
        idx = max(range(len(scores)), key=lambda i: scores[i])
        scores[idx] = round(scores[idx] + diff, 1)
    return scores


async def _auto_select(
    session: AsyncSession, course_id: int, cfg: AutoPaperConfig, total_score: float
) -> list[Question]:
    stmt = select(Question).where(
        Question.course_id == course_id, Question.status == "published"
    )
    candidates = list((await session.execute(stmt)).scalars().all())
    if cfg.kp_ids:
        candidates = [q for q in candidates if set(q.kp_ids or []) & set(cfg.kp_ids)]
    if not candidates:
        raise BadRequest("没有可用的已发布题目，请先审核通过题目")

    chosen: list[Question] = []
    chosen_ids: set[int] = set()

    # 1) 知识点覆盖：每个知识点至少 1 题
    for kp_id in cfg.kp_ids or []:
        pool = [q for q in candidates if kp_id in (q.kp_ids or []) and q.id not in chosen_ids]
        if not pool:
            continue
        pool.sort(key=lambda q: -_match_difficulty(q.difficulty, cfg.difficulty))
        chosen.append(pool[0])
        chosen_ids.add(pool[0].id)

    # 2) 题型配额
    for qtype, quota in cfg.types.items():
        current = sum(1 for q in chosen if q.type == qtype)
        need = max(0, int(quota) - current)
        pool = [q for q in candidates if q.type == qtype and q.id not in chosen_ids]
        pool.sort(key=lambda q: -_match_difficulty(q.difficulty, cfg.difficulty))
        for question in pool[:need]:
            chosen.append(question)
            chosen_ids.add(question.id)

    if not chosen:
        raise BadRequest("未筛选到符合条件的题目")

    # 3) 按知识点/难度排序，保证卷面顺序稳定
    chosen.sort(key=lambda q: ((q.kp_ids or [0])[0], q.difficulty, q.id))
    return chosen


async def create_paper(session: AsyncSession, user: User, req: PaperCreate) -> PaperOut:
    course, _ = await require_course(session, req.course_id, user, "teacher")

    if req.mode == "manual":
        if not req.question_ids:
            raise BadRequest("手动组卷需要选择题目")
        rows = await session.execute(
            select(Question).where(
                Question.id.in_(req.question_ids), Question.course_id == req.course_id
            )
        )
        found = {q.id: q for q in rows.scalars().all()}
        missing = [qid for qid in req.question_ids if qid not in found]
        if missing:
            raise BadRequest(f"题目不存在或不属于该课程：{missing}")
        questions = [found[qid] for qid in req.question_ids]
    else:
        cfg = req.config if isinstance(req.config, AutoPaperConfig) else AutoPaperConfig(
            **(req.config or {})
        )
        questions = await _auto_select(session, req.course_id, cfg, req.total_score)

    if not questions:
        raise BadRequest("试卷不能为空")

    scores = _assign_scores(questions, req.total_score)
    paper = Paper(
        course_id=req.course_id,
        creator_id=user.id,
        title=req.title,
        description=req.description,
        config=req.config.model_dump() if hasattr(req.config, "model_dump") else (req.config or {}),
        total_score=Decimal(str(round(sum(scores), 2))),
        duration_min=req.duration_min,
        status="draft",
    )
    session.add(paper)
    await session.flush()

    for seq, (question, score) in enumerate(zip(questions, scores, strict=False), start=1):
        session.add(
            PaperQuestion(
                paper_id=paper.id,
                question_id=question.id,
                seq=seq,
                score=Decimal(str(score)),
            )
        )
    await session.flush()
    logger_course = course.id
    assert logger_course
    return await get_paper(session, paper.id, user)


async def _paper_questions(
    session: AsyncSession, paper_id: int
) -> list[tuple[PaperQuestion, Question]]:
    rows = await session.execute(
        select(PaperQuestion, Question)
        .join(Question, Question.id == PaperQuestion.question_id)
        .where(PaperQuestion.paper_id == paper_id)
        .order_by(PaperQuestion.seq)
    )
    return [(pq, q) for pq, q in rows.all()]


async def get_paper(session: AsyncSession, paper_id: int, user: User) -> PaperOut:
    paper = await session.get(Paper, paper_id)
    if paper is None:
        raise NotFound("试卷不存在")
    await get_course_role(session, paper.course_id, user)
    pairs = await _paper_questions(session, paper_id)
    questions = [
        PaperQuestionOut(
            question_id=q.id,
            seq=pq.seq,
            score=float(pq.score),
            question=question_to_out(q, True),
        )
        for pq, q in pairs
    ]
    attempt = await _my_attempt(session, paper_id, user.id)
    return PaperOut.model_validate(paper).model_copy(
        update={
            "questions": questions,
            "attempt_id": attempt.id if attempt else None,
            "attempt_status": attempt.status if attempt else None,
        }
    )


async def _my_attempt(session: AsyncSession, paper_id: int, student_id: int) -> Attempt | None:
    rows = await session.execute(
        select(Attempt).where(Attempt.paper_id == paper_id, Attempt.student_id == student_id)
    )
    return rows.scalar_one_or_none()


async def get_paper_for_student(session: AsyncSession, paper_id: int, user: User) -> dict[str, Any]:
    """学生端试卷：**在服务层剥离答案**，不依赖前端过滤。"""
    paper = await session.get(Paper, paper_id)
    if paper is None:
        raise NotFound("试卷不存在")
    _, role = await get_course_role(session, paper.course_id, user)
    if role not in ("owner", "teacher") and paper.status != "published":
        raise Conflict("试卷尚未发布")

    pairs = await _paper_questions(session, paper_id)
    questions = []
    for pq, q in pairs:
        out = question_to_out(q, False).model_dump()
        out.pop("answer", None)
        out.pop("rubric", None)
        out.pop("explanation", None)
        questions.append(
            {
                "question_id": q.id,
                "seq": pq.seq,
                "score": float(pq.score),
                "type": q.type,
                "stem": q.stem,
                "options": q.options,
                "difficulty": q.difficulty,
            }
        )
    attempt = await _my_attempt(session, paper_id, user.id)
    return {
        "id": paper.id,
        "course_id": paper.course_id,
        "title": paper.title,
        "description": paper.description,
        "total_score": float(paper.total_score),
        "duration_min": paper.duration_min,
        "status": paper.status,
        "questions": questions,
        "attempt_id": attempt.id if attempt else None,
        "attempt_status": attempt.status if attempt else None,
    }


async def list_papers(session: AsyncSession, course_id: int, user: User) -> list[PaperListItem]:
    _, role = await require_course(session, course_id, user, "member")
    stmt = select(Paper).where(Paper.course_id == course_id).order_by(Paper.id.desc())
    if role not in ("owner", "teacher"):
        stmt = stmt.where(Paper.status == "published")
    papers = list((await session.execute(stmt)).scalars().all())
    out: list[PaperListItem] = []
    for paper in papers:
        count = int(
            await session.scalar(
                select(func.count()).select_from(PaperQuestion).where(
                    PaperQuestion.paper_id == paper.id
                )
            )
            or 0
        )
        attempt = await _my_attempt(session, paper.id, user.id)
        out.append(
            PaperListItem.model_validate(paper).model_copy(
                update={
                    "question_count": count,
                    "attempt_id": attempt.id if attempt else None,
                    "attempt_status": attempt.status if attempt else None,
                    "my_score": float(attempt.total_score) if attempt and attempt.total_score is not None else None,
                }
            )
        )
    return out


async def publish_paper(session: AsyncSession, paper_id: int, user: User) -> PaperOut:
    paper = await session.get(Paper, paper_id)
    if paper is None:
        raise NotFound("试卷不存在")
    await require_course(session, paper.course_id, user, "teacher")
    pairs = await _paper_questions(session, paper_id)
    if not pairs:
        raise BadRequest("试卷没有题目，无法发布")
    not_ready = [q.id for _, q in pairs if q.status != "published"]
    if not_ready:
        raise Conflict(f"以下题目尚未审核通过，不能发布：{not_ready}")
    paper.status = "published"
    session.add(paper)
    await session.flush()
    return await get_paper(session, paper_id, user)


async def paper_stats(session: AsyncSession, paper_id: int, user: User) -> dict[str, Any]:
    paper = await session.get(Paper, paper_id)
    if paper is None:
        raise NotFound("试卷不存在")
    await require_course(session, paper.course_id, user, "teacher")
    rows = await session.execute(
        select(Attempt, User.username)
        .join(User, User.id == Attempt.student_id)
        .where(Attempt.paper_id == paper_id, Attempt.status == "graded")
        .order_by(Attempt.total_score.desc())
    )
    items = []
    scores: list[float] = []
    for attempt, username in rows.all():
        score = float(attempt.total_score or 0)
        scores.append(score)
        items.append(
            {
                "attempt_id": attempt.id,
                "username": username,
                "total_score": score,
                "max_score": float(attempt.max_score or paper.total_score),
                "submitted_at": attempt.submitted_at,
            }
        )
    return {
        "paper_id": paper.id,
        "title": paper.title,
        "submitted": len(items),
        "avg_score": round(sum(scores) / len(scores), 1) if scores else 0,
        "max_score": max(scores) if scores else 0,
        "min_score": min(scores) if scores else 0,
        "items": items,
    }


__all__ = [
    "auto_select",
    "create_paper",
    "get_paper",
    "get_paper_for_student",
    "list_papers",
    "paper_stats",
    "publish_paper",
]


async def auto_select(
    session: AsyncSession, course_id: int, cfg: AutoPaperConfig, total_score: float
) -> list[Question]:
    return await _auto_select(session, course_id, cfg, total_score)
