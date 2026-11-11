"""导学老师（Tutor）状态图（计划书 9.5）。

首轮：load_context → diagnose（根因 + 前置知识点）→ retrieve → explain → cite_check → suggest_practice
追问：load_context → retrieve_followup → answer_followup
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.agents.context import AgentContext
from app.agents.graph_runtime import END, CompiledGraph, StateGraph
from app.agents.llm import get_llm_client
from app.agents.prompts import registry
from app.agents.state import TutorState
from app.core.config import settings
from app.core.logging import get_logger
from app.rag.citation import verify_refs
from app.rag.retriever import RetrievedChunk, retrieve

logger = get_logger(__name__)


def _answer_text(student_answer: Any) -> str:
    if isinstance(student_answer, dict):
        return str(student_answer.get("value") or student_answer.get("text") or "")[:500]
    return str(student_answer or "")[:500]


def _context_block(chunks: list[RetrievedChunk]) -> str:
    lines = []
    for i, chunk in enumerate(chunks, start=1):
        page = f"第{chunk.page_no}页" if chunk.page_no else (
            f"第{chunk.slide_no}页" if chunk.slide_no else "页码未知"
        )
        lines.append(
            f"[{i}] [CHUNK {chunk.chunk_id} | 《{chunk.document_name or '课件'}》{page} | "
            f"{chunk.heading_path or '正文'}]\n{chunk.content}"
        )
    return "\n\n".join(lines) or "（无可用原文）"


def build_messages(state: dict[str, Any]) -> list[dict[str, str]]:
    """组装讲解 prompt（流式与非流式共用）。"""
    ctx: AgentContext = state["_ctx"]
    question = state.get("question") or {}
    grading = state.get("grading") or {}
    rubric_detail = grading.get("rubric_detail") or []
    rubric_text = "；".join(
        f"{r.get('point', '')}（{r.get('hit', 'miss')}, {r.get('score', 0)}分）"
        for r in rubric_detail
    ) or "（无分点信息）"
    chunks = [ctx.retrieved[cid] for cid in (state.get("ref_ids") or []) if cid in ctx.retrieved]
    prompt = registry.render(
        "tutor_explain",
        course_name=ctx.course_name or "本课程",
        stem=str(question.get("stem", ""))[:600],
        answer=str(question.get("answer", ""))[:400],
        student_answer=_answer_text(state.get("answer", {}).get("value")
                                    if isinstance(state.get("answer"), dict) else state.get("answer")),
        rubric_detail=rubric_text,
        error_tags="、".join(grading.get("error_tags") or []) or "（无）",
        user_query=state.get("user_query") or "",
        context_block=_context_block(chunks),
    )
    return [
        {
            "role": "system",
            "content": "你是课程助教。讲解必须基于给定原文，事实性结论在句末用 [n] 标注来源编号；"
                       "不要背诵答案，要针对学生的具体错误讲解。",
        },
        {"role": "user", "content": prompt},
    ]


# ---------------- 节点 ----------------
async def load_context(state: dict[str, Any]) -> dict[str, Any]:
    history = list(state.get("history") or [])
    return {"history": history[-10:], "is_followup": bool(state.get("user_query"))}


async def diagnose(state: dict[str, Any]) -> dict[str, Any]:
    """错因诊断 + 根因知识点回溯（导学亮点）。"""
    ctx: AgentContext = state["_ctx"]
    question = state.get("question") or {}
    grading = state.get("grading") or {}
    answer_value = state.get("answer", {}).get("value") if isinstance(state.get("answer"), dict) else state.get("answer")
    client = get_llm_client()
    diagnosis = ""
    root_kp = None
    prereq: list[int] = []

    prompt = registry.render(
        "tutor_diagnose",
        course_name=ctx.course_name or "本课程",
        stem=str(question.get("stem", ""))[:600],
        correct_answer=str(question.get("answer", ""))[:300],
        student_answer=_answer_text(answer_value),
        error_tags="、".join(grading.get("error_tags") or []) or "（无）",
    )
    try:
        data, _ = await client.chat_json(
            "tutor_diagnose",
            [{"role": "user", "content": prompt}],
            prompt_ver=settings.PROMPT_VERSION,
        )
        diagnosis = str(data.get("diagnosis") or "")
        kp_names: dict[str, int] = ctx.extra.get("kp_names", {})
        root_kp = kp_names.get(str(data.get("root_kp") or ""))
        for name in data.get("prerequisite_kps") or []:
            if str(name) in kp_names:
                prereq.append(kp_names[str(name)])
    except Exception as exc:
        logger.warning("diagnose_failed", error=str(exc))

    if not diagnosis:
        tags = grading.get("error_tags") or []
        diagnosis = (
            f"学生在「{'、'.join(tags)}」方面存在偏差，答案没有覆盖评分点要求的关键环节。"
            if tags
            else "学生答案与标准答案的关键环节不一致。"
        )
    if root_kp is None:
        kp_ids = question.get("kp_ids") or []
        root_kp = int(kp_ids[0]) if kp_ids else None
    return {"diagnosis": diagnosis, "root_kp_id": root_kp, "prerequisite_kps": prereq[:2],
            "is_followup": False}


async def retrieve_node(state: dict[str, Any]) -> dict[str, Any]:
    ctx: AgentContext = state["_ctx"]
    question = state.get("question") or {}
    kp_names: dict[int, str] = ctx.extra.get("kp_name_by_id", {})
    names = [kp_names.get(int(k), "") for k in [state.get("root_kp_id")] + list(state.get("prerequisite_kps") or [])]
    names = [n for n in names if n]
    query = " ".join(names) or str(question.get("stem", ""))[:120]
    # 导学是 SSE 流式交互，首字延迟优先，显式不启用重排（见 docs/experiments/retrieval-upgrade.md）
    chunks = await retrieve(ctx.session, ctx.course_id, query, top_k=5, use_rerank=False)
    ctx.remember(chunks)
    return {"refs": [c.to_ref() for c in chunks], "ref_ids": [c.chunk_id for c in chunks]}


async def retrieve_followup(state: dict[str, Any]) -> dict[str, Any]:
    ctx: AgentContext = state["_ctx"]
    question = state.get("question") or {}
    query = f"{state.get('user_query') or ''} {question.get('stem', '')[:80]}".strip()
    # 导学是 SSE 流式交互，首字延迟优先，显式不启用重排（见 docs/experiments/retrieval-upgrade.md）
    chunks = await retrieve(ctx.session, ctx.course_id, query, top_k=5, use_rerank=False)
    ctx.remember(chunks)
    existing = {int(r["chunk_id"]) for r in state.get("refs") or []}
    merged = list(state.get("refs") or []) + [
        c.to_ref() for c in chunks if c.chunk_id not in existing
    ]
    return {"refs": merged[:6], "ref_ids": [int(r["chunk_id"]) for r in merged[:6]]}


async def explain(state: dict[str, Any]) -> dict[str, Any]:
    client = get_llm_client()
    messages = build_messages(state)
    result = await client.chat(
        "tutor",
        messages,
        meta={
            "stem": (state.get("question") or {}).get("stem", ""),
            "student_answer": _answer_text(
                (state.get("answer") or {}).get("value")
                if isinstance(state.get("answer"), dict)
                else state.get("answer")
            ),
            "error_tags": (state.get("grading") or {}).get("error_tags") or [],
            "refs": state.get("refs") or [],
            "anchor": (state.get("refs") or [{}])[0].get("quote", "") if state.get("refs") else "",
            "course_name": state["_ctx"].course_name,
            "user_query": state.get("user_query"),
        },
        prompt_ver=settings.PROMPT_VERSION,
    )
    return {"explanation": result.text, "final_answer": result.text, "tokens": result.total_tokens}


async def cite_check(state: dict[str, Any]) -> dict[str, Any]:
    """复用引用校验关卡 1、2（交互场景不做关卡 3，成本高）。"""
    ctx: AgentContext = state["_ctx"]
    refs = state.get("refs") or []
    if not refs:
        return {"refs": []}
    outcome = verify_refs(refs, ctx.retrieved)
    if not outcome.ok:
        logger.warning("tutor_citation_failed", reason=outcome.reason)
        return {"refs": [r for r in refs if int(r.get("chunk_id", 0)) in ctx.retrieved]}
    return {"refs": outcome.refs}


async def suggest_practice(state: dict[str, Any]) -> dict[str, Any]:
    """同 kp、未做过的 2 道题（纯 DB 查询，不调 LLM）。"""
    ctx: AgentContext = state["_ctx"]
    from app.db.models import Answer, Attempt, Question

    question = state.get("question") or {}
    kp_ids = [int(k) for k in (question.get("kp_ids") or [])]
    if not kp_ids:
        return {"practice": []}
    answered = select(Answer.question_id).join(Attempt, Attempt.id == Answer.attempt_id).where(
        Attempt.student_id == (ctx.user_id or 0)
    )
    stmt = (
        select(Question)
        .where(Question.course_id == ctx.course_id, Question.status == "published")
        .where(Question.id.not_in(answered))
        .where(Question.id != int(question.get("id") or 0))
        .limit(12)
    )
    rows = (await ctx.session.execute(stmt)).scalars().all()
    picked = [q for q in rows if set(q.kp_ids or []) & set(kp_ids)][:2]
    practice = [
        {
            "question_id": q.id,
            "type": q.type,
            "stem": q.stem[:120],
            "difficulty": q.difficulty,
        }
        for q in picked
    ]
    return {"practice": practice}


async def answer_followup(state: dict[str, Any]) -> dict[str, Any]:
    client = get_llm_client()
    refs = state.get("refs") or []
    ctx: AgentContext = state["_ctx"]
    prompt = registry.render(
        "tutor_explain",
        course_name=ctx.course_name or "本课程",
        stem=str((state.get("question") or {}).get("stem", ""))[:600],
        answer=str((state.get("question") or {}).get("answer", ""))[:400],
        student_answer=_answer_text((state.get("answer") or {}).get("value")),
        rubric_detail=str((state.get("grading") or {}).get("rubric_detail", ""))[:400],
        error_tags="、".join((state.get("grading") or {}).get("error_tags") or []) or "（无）",
        user_query=state.get("user_query") or "",
        context_block=_context_block(
            [ctx.retrieved[int(r["chunk_id"])] for r in refs if int(r["chunk_id"]) in ctx.retrieved]
        ),
    )
    result = await client.chat(
        "tutor",
        [
            {"role": "system", "content": "你是课程助教，回答学生追问，聚焦当前问题，不重复整段讲解。"},
            {"role": "user", "content": prompt},
        ],
        meta={
            "stem": (state.get("question") or {}).get("stem", ""),
            "student_answer": _answer_text((state.get("answer") or {}).get("value")),
            "error_tags": (state.get("grading") or {}).get("error_tags") or [],
            "refs": refs,
            "anchor": (refs or [{}])[0].get("quote", "") if refs else "",
            "course_name": ctx.course_name,
            "user_query": state.get("user_query"),
        },
        prompt_ver=settings.PROMPT_VERSION,
    )
    return {"explanation": result.text, "final_answer": result.text, "tokens": result.total_tokens}


def _route_first(state: dict[str, Any]) -> str:
    return "followup" if state.get("user_query") else "first"


def build_graph() -> CompiledGraph:
    graph = StateGraph(TutorState)
    graph.add_node("load_context", load_context)
    graph.add_node("diagnose", diagnose)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("explain", explain)
    graph.add_node("cite_check", cite_check)
    graph.add_node("suggest_practice", suggest_practice)
    graph.add_node("retrieve_followup", retrieve_followup)
    graph.add_node("answer_followup", answer_followup)

    graph.add_conditional_edges(
        "load_context", _route_first, {"first": "diagnose", "followup": "retrieve_followup"}
    )
    graph.add_edge("diagnose", "retrieve")
    graph.add_edge("retrieve", "explain")
    graph.add_edge("explain", "cite_check")
    graph.add_edge("cite_check", "suggest_practice")
    graph.add_edge("suggest_practice", END)
    graph.add_edge("retrieve_followup", "answer_followup")
    graph.add_edge("answer_followup", "cite_check")
    graph.set_entry_point("load_context")
    return graph.compile()


TUTOR_GRAPH: CompiledGraph = build_graph()
