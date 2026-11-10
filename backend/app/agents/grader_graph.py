"""阅卷官（Grader）状态图（计划书 9.4）。

客观题走规则判分；主观题三步法：要点抽取 → 逐点评分 → 一致性复核（低置信转人工）。
"""

from __future__ import annotations

import statistics
from typing import Any

from app.agents.context import AgentContext
from app.agents.graph_runtime import END, CompiledGraph, StateGraph
from app.agents.llm import get_llm_client
from app.agents.prompts import registry
from app.agents.state import GraderState
from app.agents.validators import validate_grade
from app.core.config import settings
from app.core.logging import get_logger
from app.rag.retriever import retrieve

logger = get_logger(__name__)

OBJECTIVE_TYPES = ("single", "multiple", "judge")


def normalize_objective(value: Any) -> Any:
    if isinstance(value, str):
        v = value.strip()
        if v.lower() in ("true", "对", "正确", "t", "yes"):
            return True
        if v.lower() in ("false", "错", "错误", "f", "no"):
            return False
        return v.upper()
    if isinstance(value, list):
        return sorted(normalize_objective(v) for v in value)
    return value


def grade_objective(question: dict[str, Any], student_answer: Any, max_score: float) -> dict[str, Any]:
    """规则判分：空答 0 分；多选严格全对（部分给分作为 P1）。"""
    qtype = question.get("type")
    answer = question.get("answer")
    if student_answer is None or student_answer == "" or student_answer == []:
        return {
            "score": 0.0,
            "is_correct": False,
            "graded_by": "rule",
            "feedback": "本题未作答",
            "error_tags": ["未作答"],
            "rubric_detail": [],
            "confidence": 1.0,
            "needs_human": False,
        }
    if qtype == "multiple":
        expected = set(normalize_objective(answer) or [])
        got = set(normalize_objective(student_answer) or [])
        correct = expected == got
    else:
        correct = normalize_objective(student_answer) == normalize_objective(answer)
    return {
        "score": float(max_score) if correct else 0.0,
        "is_correct": correct,
        "graded_by": "rule",
        "feedback": "" if correct else (question.get("explanation") or "答案与标准答案不一致"),
        "error_tags": [] if correct else ["概念混淆"],
        "rubric_detail": [],
        "confidence": 1.0,
        "needs_human": False,
    }


def _rubric_block(rubric: list[dict[str, Any]]) -> str:
    lines = []
    for i, item in enumerate(rubric, start=1):
        keywords = "、".join(item.get("keywords") or [])
        lines.append(
            f"{i}. {item.get('point', '')}（{item.get('score', 0)}分"
            + (f"，关键词：{keywords}" if keywords else "")
            + ")"
        )
    return "\n".join(lines)


def _context_block(chunks: list[Any]) -> str:
    lines = []
    for chunk in chunks:
        page = f"第{chunk.page_no}页" if chunk.page_no else "页码未知"
        lines.append(
            f"[CHUNK {chunk.chunk_id} | 《{chunk.document_name or '课件'}》{page}]\n{chunk.content}"
        )
    return "\n\n".join(lines) or "（无可用参考原文）"


# ---------------- 节点 ----------------
async def route(state: dict[str, Any]) -> dict[str, Any]:
    return {}


async def rule_grade(state: dict[str, Any]) -> dict[str, Any]:
    result = grade_objective(
        state.get("question") or {},
        state.get("student_answer"),
        float(state.get("max_score") or 0),
    )
    return {
        "score": result["score"],
        "graded_by": "rule",
        "feedback": result["feedback"],
        "error_tags": result["error_tags"],
        "rubric_hits": [],
        "confidence": 1.0,
        "needs_human": False,
        "scores": [result["score"]],
    }


async def extract_points(state: dict[str, Any]) -> dict[str, Any]:
    """要点抽取：只拆点不评分，产出可核查的中间结果。"""
    client = get_llm_client()
    answer_text = str(state.get("student_answer") or "")
    if not answer_text.strip():
        return {"extracted_points": []}
    prompt = registry.render("grader_extract", student_answer=answer_text[:2000])
    try:
        data, _ = await client.chat_json(
            "grader_extract",
            [{"role": "user", "content": prompt}],
            temperature=0.0,
            prompt_ver=settings.PROMPT_VERSION,
        )
        points = [p.get("text", "") for p in (data.get("points") or []) if p.get("text")]
    except Exception as exc:
        logger.warning("extract_points_failed", error=str(exc))
        points = []
    if not points:
        points = [p.strip() for p in answer_text.replace("\n", "。").split("。") if len(p.strip()) > 4][:6]
    return {"extracted_points": points}


async def retrieve_rubric(state: dict[str, Any]) -> dict[str, Any]:
    ctx: AgentContext = state["_ctx"]
    question = state.get("question") or {}
    query = f"{question.get('stem', '')} {question.get('explanation', '')}".strip()
    if not query:
        return {"retrieved_refs": []}
    try:
        chunks = await retrieve(ctx.session, ctx.course_id, query[:300], top_k=5)
    except Exception as exc:
        logger.warning("grader_retrieve_failed", error=str(exc))
        chunks = []
    ctx.remember(chunks)
    return {"retrieved_refs": [c.to_dict() for c in chunks]}


async def _grade_once(state: dict[str, Any], temperature: float) -> dict[str, Any] | None:
    ctx: AgentContext = state["_ctx"]
    client = get_llm_client()
    question = state.get("question") or {}
    max_score = float(state.get("max_score") or 0)
    rubric = question.get("rubric") or []
    chunks = [ctx.retrieved[int(r["chunk_id"])] for r in state.get("retrieved_refs") or []
              if int(r["chunk_id"]) in ctx.retrieved]
    prompt = registry.render(
        "grader_subjective",
        course_name=ctx.course_name or "本课程",
        rubric_block=_rubric_block(rubric),
        student_answer=str(state.get("student_answer") or "")[:3000],
        context_block=_context_block(chunks),
        max_score=max_score,
    )
    data, _ = await client.chat_json(
        "grader_subjective",
        [
            {"role": "system", "content": "你是严格客观的阅卷教师，只输出 JSON。"},
            {"role": "user", "content": prompt},
        ],
        temperature=temperature,
        meta={
            "rubric": rubric,
            "student_answer": state.get("student_answer"),
            "max_score": max_score,
            "points": state.get("extracted_points") or [],
        },
        prompt_ver=settings.PROMPT_VERSION,
    )
    result, error = validate_grade(data, max_score)
    if error:
        logger.warning("grade_validate_failed", error=error)
        return None
    return result


async def llm_grade(state: dict[str, Any]) -> dict[str, Any]:
    if not str(state.get("student_answer") or "").strip():
        return {
            "score": 0.0,
            "graded_by": "rule",
            "feedback": "本题未作答",
            "error_tags": ["未作答"],
            "confidence": 1.0,
            "needs_human": False,
            "scores": [0.0],
        }
    result = await _grade_once(state, settings.LLM_TEMPERATURE_GRADE)
    if result is None:
        return {
            "score": 0.0,
            "graded_by": "agent",
            "feedback": "自动评分失败，已标记待人工评分",
            "error_tags": [],
            "confidence": 0.0,
            "needs_human": True,
            "scores": [0.0],
        }
    return {
        "score": float(result["score"]),
        "graded_by": "agent",
        "feedback": result.get("feedback", ""),
        "error_tags": result.get("error_tags", []),
        "rubric_hits": result.get("rubric_detail", []),
        "confidence": float(result.get("confidence", 0.7)),
        "scores": [float(result["score"])],
        "retry_count": 0,
    }


async def consistency_check(state: dict[str, Any]) -> dict[str, Any]:
    """同模型 temperature=0 复评：差值 ≤15% 取均值；否则第三次取中位数；极差>30% 转人工。"""
    max_score = float(state.get("max_score") or 0) or 1.0
    scores: list[float] = list(state.get("scores") or [])

    second = await _grade_once(state, 0.0)
    if second is not None:
        scores.append(float(second["score"]))
    if len(scores) < 2:
        return {"scores": [], "needs_human": True, "confidence": 0.0,
                "feedback": state.get("feedback") or "自动评分结果不稳定，建议人工复核"}

    if abs(scores[0] - scores[1]) > max_score * 0.15:
        third = await _grade_once(state, 0.0)
        if third is not None:
            scores.append(float(third["score"]))

    spread = max(scores) - min(scores)
    if spread > max_score * 0.3:
        return {
            "scores": [],
            "score": round(statistics.median(scores), 2),
            "needs_human": True,
            "confidence": 0.4,
            "warnings": [f"三次评分极差 {spread:.1f} 分（>30%），已标记建议人工复核"],
        }

    final = round(statistics.median(scores) * 2) / 2 if len(scores) >= 3 else round(
        statistics.fmean(scores) * 2
    ) / 2
    confidence = max(0.5, min(0.98, 1 - spread / max_score))
    return {
        "scores": [],
        "score": min(final, max_score),
        "needs_human": False,
        "confidence": round(confidence, 2),
    }


async def mark_human(state: dict[str, Any]) -> dict[str, Any]:
    return {"needs_human": True, "confidence": min(float(state.get("confidence") or 0.3), 0.5)}


async def aggregate(state: dict[str, Any]) -> dict[str, Any]:
    max_score = float(state.get("max_score") or 0)
    score = float(state.get("score") or 0)
    score = max(0.0, min(score, max_score))
    is_correct = score >= max_score * 0.999
    return {
        "score": score,
        "graded_by": state.get("graded_by") or "agent",
        "rubric_hits": state.get("rubric_hits") or [],
        "feedback": state.get("feedback") or "",
        "error_tags": state.get("error_tags") or [],
        "confidence": float(state.get("confidence") or 0.7),
        "needs_human": bool(state.get("needs_human")),
        "is_correct": is_correct,
    }


def _route_by_type(state: dict[str, Any]) -> str:
    qtype = (state.get("question") or {}).get("type")
    return "rule" if qtype in OBJECTIVE_TYPES else "subjective"


def _after_consistency(state: dict[str, Any]) -> str:
    return "human" if state.get("needs_human") else "aggregate"


def build_graph() -> CompiledGraph:
    graph = StateGraph(GraderState)
    graph.add_node("route", route)
    graph.add_node("rule_grade", rule_grade)
    graph.add_node("extract_points", extract_points)
    graph.add_node("retrieve_rubric", retrieve_rubric)
    graph.add_node("llm_grade", llm_grade)
    graph.add_node("consistency_check", consistency_check)
    graph.add_node("mark_human", mark_human)
    graph.add_node("aggregate", aggregate)

    graph.add_conditional_edges(
        "route", _route_by_type, {"rule": "rule_grade", "subjective": "extract_points"}
    )
    graph.add_edge("extract_points", "retrieve_rubric")
    graph.add_edge("retrieve_rubric", "llm_grade")
    graph.add_edge("llm_grade", "consistency_check")
    graph.add_conditional_edges(
        "consistency_check", _after_consistency,
        {"human": "mark_human", "aggregate": "aggregate"},
    )
    graph.add_edge("rule_grade", "aggregate")
    graph.add_edge("mark_human", "aggregate")
    graph.add_edge("aggregate", END)
    graph.set_entry_point("route")
    return graph.compile()


GRADER_GRAPH: CompiledGraph = build_graph()
