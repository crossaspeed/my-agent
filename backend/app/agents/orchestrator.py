"""编排层：对外暴露三个智能体入口，隐藏状态图细节（计划书 9.6）。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.context import AgentContext
from app.agents.grader_graph import GRADER_GRAPH
from app.agents.llm import get_llm_client
from app.agents.question_graph import QUESTION_GRAPH
from app.agents.tutor_graph import (
    TUTOR_GRAPH,
    build_messages,
    cite_check,
    diagnose,
    load_context,
    retrieve_followup,
    retrieve_node,
    suggest_practice,
)
from app.core.config import settings
from app.core.logging import get_logger
from app.rag.retriever import RetrievedChunk

logger = get_logger(__name__)

DIFFICULTY_MAP = {"easy": 2, "medium": 3, "hard": 5}


def build_kp_specs(
    kp_ids: list[int],
    kp_names: dict[int, str],
    types: dict[str, int],
    difficulty: dict[str, float],
    score_per_question: float,
) -> list[dict[str, Any]]:
    """把「题型配比 × 知识点」展开成出题任务清单（每项一次 LLM 调用）。"""
    if not kp_ids:
        return []
    specs: list[dict[str, Any]] = []
    for qtype, count in types.items():
        if count <= 0:
            continue
        base, remainder = divmod(int(count), len(kp_ids))
        for i, kp_id in enumerate(kp_ids):
            n = base + (1 if i < remainder else 0)
            if n <= 0:
                continue
            specs.append(
                {
                    "kp_id": kp_id,
                    "name": kp_names.get(kp_id, f"知识点{kp_id}"),
                    "count": n,
                    "type": qtype,
                    "difficulty": _pick_difficulty(n, difficulty),
                    "score": score_per_question,
                }
            )
    return specs


def _pick_difficulty(n: int, dist: dict[str, float]) -> int:
    total = sum(max(0.0, v) for v in dist.values()) or 1.0
    hard = round(n * max(0.0, dist.get("hard", 0.2)) / total)
    easy = round(n * max(0.0, dist.get("easy", 0.2)) / total)
    medium = max(0, n - hard - easy)
    if medium > 0:
        return DIFFICULTY_MAP["medium"]
    if hard > 0:
        return DIFFICULTY_MAP["hard"]
    return DIFFICULTY_MAP["easy"]


class AgentOrchestrator:
    """所有智能体调用的唯一入口。"""

    async def generate_questions(
        self,
        session: AsyncSession,
        course_id: int,
        course_name: str,
        kp_specs: list[dict[str, Any]],
        requirements: str = "",
        doc_ids: list[int] | None = None,
        score_per_question: float = 5.0,
        trace_id: str = "",
    ) -> dict[str, Any]:
        ctx = AgentContext(
            session=session, course_id=course_id, course_name=course_name, trace_id=trace_id
        )
        state: dict[str, Any] = {
            "_ctx": ctx,
            "course_id": course_id,
            "course_name": course_name,
            "kp_specs": kp_specs,
            "requirements": requirements,
            "doc_ids": doc_ids,
            "score_per_question": score_per_question,
            "repair_round": 0,
            "trace_id": trace_id,
        }
        result = await QUESTION_GRAPH.invoke(state, config={"configurable": {"thread_id": trace_id}})
        return {
            "questions": result.get("final_questions") or [],
            "warnings": list(dict.fromkeys(result.get("warnings") or [])),
            "retrieval_map": result.get("retrieval_map") or {},
            "trace": result.get("trace") or [],
        }

    async def grade_answer(
        self,
        session: AsyncSession,
        course_id: int,
        course_name: str,
        question: dict[str, Any],
        student_answer: Any,
        max_score: float,
        trace_id: str = "",
    ) -> dict[str, Any]:
        ctx = AgentContext(
            session=session, course_id=course_id, course_name=course_name, trace_id=trace_id
        )
        state: dict[str, Any] = {
            "_ctx": ctx,
            "course_id": course_id,
            "course_name": course_name,
            "question": question,
            "student_answer": student_answer,
            "max_score": max_score,
            "scores": [],
            "warnings": [],
            "trace_id": trace_id,
        }
        result = await GRADER_GRAPH.invoke(state, config={"configurable": {"thread_id": trace_id}})
        return {
            "score": result.get("score", 0.0),
            "is_correct": result.get("is_correct"),
            "rubric_detail": result.get("rubric_hits") or [],
            "feedback": result.get("feedback") or "",
            "error_tags": result.get("error_tags") or [],
            "graded_by": result.get("graded_by") or "agent",
            "confidence": result.get("confidence", 0.7),
            "needs_human": result.get("needs_human", False),
            "warnings": result.get("warnings") or [],
        }

    # ---------------- 导学 ----------------
    def _tutor_state(
        self,
        session: AsyncSession,
        course_id: int,
        course_name: str,
        question: dict[str, Any],
        answer: dict[str, Any],
        grading: dict[str, Any],
        history: list[dict[str, Any]],
        user_query: str | None,
        kp_name_by_id: dict[int, str],
        student_id: int | None = None,
        session_id: int = 0,
    ) -> dict[str, Any]:
        ctx = AgentContext(
            session=session,
            course_id=course_id,
            course_name=course_name,
            user_id=student_id,
            extra={"kp_name_by_id": kp_name_by_id, "kp_names": {v: k for k, v in kp_name_by_id.items()}},
        )
        return {
            "_ctx": ctx,
            "session_id": session_id,
            "course_id": course_id,
            "course_name": course_name,
            "question": question,
            "answer": answer or {},
            "grading": grading or {},
            "history": history or [],
            "user_query": user_query,
            "refs": [],
            "practice": [],
        }

    async def tutor_answer(self, **kwargs: Any) -> dict[str, Any]:
        """非流式（首轮开场、异步生成）。"""
        state = self._tutor_state(**kwargs)
        return await TUTOR_GRAPH.invoke(state)

    async def tutor_stream(self, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        """SSE 流式：先诊断/检索，再逐 token 输出，最后下发 refs 与推荐练习。"""
        state = self._tutor_state(**kwargs)
        state.update(await load_context(state))
        if state.get("user_query"):
            state.update(await retrieve_followup(state))
        else:
            state.update(await diagnose(state))
            state.update(await retrieve_node(state))

        messages = build_messages(state)
        client = get_llm_client()
        meta = {
            "stem": (state.get("question") or {}).get("stem", ""),
            "student_answer": _answer_text((state.get("answer") or {}).get("value")),
            "error_tags": (state.get("grading") or {}).get("error_tags") or [],
            "refs": state.get("refs") or [],
            "anchor": (state.get("refs") or [{}])[0].get("quote", "") if state.get("refs") else "",
            "course_name": state["_ctx"].course_name,
            "user_query": state.get("user_query"),
        }
        parts: list[str] = []
        async for delta in client.stream_chat(
            "tutor", messages, meta=meta, prompt_ver=settings.PROMPT_VERSION
        ):
            parts.append(delta)
            yield {"event": "token", "data": {"delta": delta}}

        state["explanation"] = "".join(parts)
        state.update(await cite_check(state))
        state.update(await suggest_practice(state))
        yield {
            "event": "refs",
            "data": {"refs": state.get("refs") or [], "practice": state.get("practice") or [],
                     "diagnosis": state.get("diagnosis") or ""},
        }
        yield {
            "event": "done",
            "data": {"content": state["explanation"], "refs": state.get("refs") or [],
                     "practice": state.get("practice") or []},
        }

    @staticmethod
    def resolve_refs(state: dict[str, Any]) -> list[RetrievedChunk]:
        ctx: AgentContext = state["_ctx"]
        return list(ctx.retrieved.values())


def _answer_text(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("value") or value.get("text") or "")[:500]
    return str(value or "")[:500]


orchestrator = AgentOrchestrator()
