"""课程、成员与知识点服务。"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequest, Conflict, NotFound
from app.db.models import (
    ChunkKnowledgePoint,
    Course,
    CourseMember,
    Document,
    DocumentChunk,
    KnowledgePoint,
    Paper,
    Question,
    User,
)
from app.schemas.course import (
    CourseCreate,
    CourseOut,
    CourseStats,
    CourseUpdate,
    KnowledgePointCreate,
    KnowledgePointOut,
    KnowledgePointUpdate,
    MemberOut,
)
from app.services.access import get_course_role, require_course


async def _stats(session: AsyncSession, course_id: int) -> CourseStats:
    async def _count(model: type, *where: object) -> int:
        stmt = select(func.count()).select_from(model)
        for cond in where:
            stmt = stmt.where(cond)  # type: ignore[arg-type]
        return int(await session.scalar(stmt) or 0)

    students = int(
        await session.scalar(
            select(func.count()).select_from(CourseMember).where(
                CourseMember.course_id == course_id, CourseMember.role == "student"
            )
        )
        or 0
    )
    return CourseStats(
        documents=await _count(Document, Document.course_id == course_id),
        questions=await _count(Question, Question.course_id == course_id),
        papers=await _count(Paper, Paper.course_id == course_id),
        students=students,
        knowledge_points=await _count(KnowledgePoint, KnowledgePoint.course_id == course_id),
        chunks=await _count(DocumentChunk, DocumentChunk.course_id == course_id),
    )


async def create_course(session: AsyncSession, user: User, req: CourseCreate) -> CourseOut:
    dup = await session.execute(select(Course).where(Course.code == req.code))
    if dup.scalar_one_or_none() is not None:
        raise Conflict("课程编号已存在")
    course = Course(
        code=req.code,
        name=req.name,
        description=req.description,
        owner_id=user.id,
        settings=req.settings or {},
    )
    session.add(course)
    await session.flush()
    return CourseOut.model_validate(course).model_copy(
        update={"my_role": "owner", "stats": await _stats(session, course.id)}
    )


async def list_courses(session: AsyncSession, user: User) -> list[CourseOut]:
    owned = await session.execute(select(Course).where(Course.owner_id == user.id))
    courses = list(owned.scalars().all())
    joined = await session.execute(
        select(Course, CourseMember.role)
        .join(CourseMember, CourseMember.course_id == Course.id)
        .where(CourseMember.user_id == user.id)
    )
    role_map: dict[int, str] = {}
    for course, role in joined.all():
        role_map[course.id] = role
        if all(c.id != course.id for c in courses):
            courses.append(course)

    out: list[CourseOut] = []
    for course in courses:
        role = "owner" if course.owner_id == user.id else role_map.get(course.id, "student")
        out.append(
            CourseOut.model_validate(course).model_copy(
                update={"my_role": role, "stats": await _stats(session, course.id)}
            )
        )
    out.sort(key=lambda c: c.id)
    return out


async def get_detail(session: AsyncSession, course_id: int, user: User) -> CourseOut:
    course, role = await get_course_role(session, course_id, user)
    return CourseOut.model_validate(course).model_copy(
        update={"my_role": role, "stats": await _stats(session, course.id)}
    )


async def update_course(
    session: AsyncSession, course_id: int, user: User, req: CourseUpdate
) -> CourseOut:
    course, _ = await require_course(session, course_id, user, "owner")
    if req.name is not None:
        course.name = req.name
    if req.description is not None:
        course.description = req.description
    if req.settings is not None:
        course.settings = req.settings
    session.add(course)
    await session.flush()
    return await get_detail(session, course_id, user)


async def add_members(
    session: AsyncSession, course_id: int, user: User, usernames: list[str]
) -> dict[str, list[str]]:
    _, _role = await require_course(session, course_id, user, "owner")
    rows = await session.execute(select(User).where(User.username.in_(usernames)))
    users = {u.username: u for u in rows.scalars().all()}
    existing = await session.execute(
        select(CourseMember.user_id).where(CourseMember.course_id == course_id)
    )
    have = {int(r[0]) for r in existing.all()}

    added: list[str] = []
    skipped: list[str] = []
    for username in usernames:
        target = users.get(username)
        if target is None or target.id in have:
            skipped.append(username)
            continue
        session.add(CourseMember(course_id=course_id, user_id=target.id, role="student"))
        have.add(target.id)
        added.append(username)
    await session.flush()
    return {"added": added, "skipped": skipped}


async def list_members(session: AsyncSession, course_id: int, user: User) -> list[MemberOut]:
    await require_course(session, course_id, user, "member")
    rows = await session.execute(
        select(User, CourseMember.role)
        .join(CourseMember, CourseMember.user_id == User.id)
        .where(CourseMember.course_id == course_id)
        .order_by(CourseMember.role, User.id)
    )
    return [
        MemberOut(user_id=u.id, username=u.username, real_name=u.real_name, role=r)
        for u, r in rows.all()
    ]


# ---------------- 知识点 ----------------
async def get_kp_tree(session: AsyncSession, course_id: int, user: User) -> list[KnowledgePointOut]:
    await require_course(session, course_id, user, "member")
    rows = await session.execute(
        select(KnowledgePoint)
        .where(KnowledgePoint.course_id == course_id)
        .order_by(KnowledgePoint.sort_order, KnowledgePoint.id)
    )
    items = list(rows.scalars().all())
    counts = await session.execute(
        select(ChunkKnowledgePoint.kp_id, func.count())
        .where(ChunkKnowledgePoint.kp_id.in_([kp.id for kp in items] or [0]))
        .group_by(ChunkKnowledgePoint.kp_id)
    )
    count_map = {int(k): int(v) for k, v in counts.all()}
    nodes = {
        kp.id: KnowledgePointOut.model_validate(kp).model_copy(
            update={"chunk_count": count_map.get(kp.id, 0)}
        )
        for kp in items
    }
    roots: list[KnowledgePointOut] = []
    for kp in items:
        node = nodes[kp.id]
        if kp.parent_id and kp.parent_id in nodes:
            nodes[kp.parent_id].children.append(node)
        else:
            roots.append(node)
    return roots


async def list_kp_flat(session: AsyncSession, course_id: int) -> list[KnowledgePoint]:
    rows = await session.execute(
        select(KnowledgePoint).where(KnowledgePoint.course_id == course_id).order_by(KnowledgePoint.id)
    )
    return list(rows.scalars().all())


async def create_kp(
    session: AsyncSession, course_id: int, user: User, req: KnowledgePointCreate
) -> KnowledgePointOut:
    await require_course(session, course_id, user, "teacher")
    if req.parent_id:
        parent = await session.get(KnowledgePoint, req.parent_id)
        if parent is None or parent.course_id != course_id:
            raise BadRequest("父知识点不存在")
    kp = KnowledgePoint(
        course_id=course_id,
        parent_id=req.parent_id,
        name=req.name,
        description=req.description,
        importance=req.importance,
        sort_order=req.sort_order,
    )
    session.add(kp)
    await session.flush()
    return KnowledgePointOut.model_validate(kp)


async def update_kp(
    session: AsyncSession, kp_id: int, user: User, req: KnowledgePointUpdate
) -> KnowledgePointOut:
    kp = await session.get(KnowledgePoint, kp_id)
    if kp is None:
        raise NotFound("知识点不存在")
    await require_course(session, kp.course_id, user, "teacher")
    for field in ("name", "description", "importance", "sort_order", "parent_id"):
        value = getattr(req, field)
        if value is not None:
            setattr(kp, field, value)
    session.add(kp)
    await session.flush()
    return KnowledgePointOut.model_validate(kp)


async def delete_kp(session: AsyncSession, kp_id: int, user: User) -> None:
    kp = await session.get(KnowledgePoint, kp_id)
    if kp is None:
        raise NotFound("知识点不存在")
    await require_course(session, kp.course_id, user, "teacher")
    await session.delete(kp)


async def auto_extract_kps(
    session: AsyncSession, course_id: int, user: User, max_points: int = 12
) -> list[KnowledgePointOut]:
    """从已解析分块的 heading_path 自动抽取知识点树（P1，启发式 + 去重）。"""
    course, _ = await require_course(session, course_id, user, "teacher")
    rows = await session.execute(
        select(DocumentChunk.heading_path)
        .where(DocumentChunk.course_id == course_id, DocumentChunk.heading_path.is_not(None))
        .limit(2000)
    )
    paths = [p for (p,) in rows.all() if p]
    if not paths:
        raise BadRequest("知识库尚无标题结构，请先上传并解析课件")

    existing = {kp.name for kp in await list_kp_flat(session, course_id)}
    counter: dict[str, int] = {}
    for path in paths:
        parts = [p.strip() for p in path.split(">") if p.strip()]
        for depth, name in enumerate(parts[:2]):
            key = name if depth == 0 else f"{parts[0]} > {name}"
            if len(name) > 40 or name in existing:
                continue
            counter[key] = counter.get(key, 0) + 1

    created: list[KnowledgePointOut] = []
    parent_ids: dict[str, int] = {}
    for key, count in sorted(counter.items(), key=lambda kv: -kv[1])[:max_points]:
        if " > " in key:
            parent_name, name = key.split(" > ", 1)
            parent_id = parent_ids.get(parent_name)
            if parent_id is None:
                continue
            kp = KnowledgePoint(
                course_id=course_id, parent_id=parent_id, name=name[:128],
                importance=3, sort_order=count,
            )
        else:
            kp = KnowledgePoint(
                course_id=course_id, name=key[:128], importance=4, sort_order=count
            )
        session.add(kp)
        await session.flush()
        if " > " not in key:
            parent_ids[key] = kp.id
        created.append(KnowledgePointOut.model_validate(kp))
    if created:
        from app.rag import bm25_index

        bm25_index.invalidate(course.id)
    return created
