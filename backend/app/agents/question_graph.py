"""出题官（Question Generator）状态图（计划书 9.3）。

plan → retrieve → draft → validate_schema → verify_citation → (repair 回环) → score_quality
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.agents.context import AgentContext
from app.agents.graph_runtime import END, CompiledGraph, StateGraph
from app.agents.llm import get_llm_client
from app.agents.prompts import registry
from app.agents.state import QuestionGenState
from app.agents.validators import validate_drafts
from app.core.config import settings
from app.core.exceptions import KnowledgeNotCovered
from app.core.logging import get_logger
from app.rag import rerank
from app.rag.citation import citation_coverage, verify_refs
from app.rag.retriever import RetrievedChunk, retrieve

logger = get_logger(__name__)

TYPE_LABEL = {
    "single": "单选题",
    "multiple": "多选题",
    "judge": "判断题",
    "short": "简答题",
    "essay": "论述题",
}
DIFFICULTY_LABEL = {1: "很易", 2: "较易", 3: "中等", 4: "较难", 5: "很难"}


def context_block(chunks: list[RetrievedChunk]) -> str:
    lines: list[str] = []
    for chunk in chunks:
        page = f"第{chunk.page_no}页" if chunk.page_no else (
            f"第{chunk.slide_no}页" if chunk.slide_no else "页码未知"
        )
        header = f"[CHUNK {chunk.chunk_id} | 《{chunk.document_name or '课件'}》{page} | {chunk.heading_path or '正文'}]"
        lines.append(f"{header}\n{chunk.content}")
    return "\n\n".join(lines)


def _chunks_for(state: dict[str, Any], kp_id: int) -> list[RetrievedChunk]:
    ctx: AgentContext = state["_ctx"]
    refs = (state.get("retrieval_map") or {}).get(kp_id) or []
    out = []
    for ref in refs:
        chunk = ctx.retrieved.get(int(ref["chunk_id"]))
        if chunk:
            out.append(chunk)
    return out


# ---------------- 节点 ----------------
async def plan(state: dict[str, Any]) -> dict[str, Any]:
    """把知识点扩写成 2-3 条检索式；LLM 失败时退化为模板查询。"""
    ctx: AgentContext = state["_ctx"]
    specs = state.get("kp_specs") or []
    if not specs:
        raise KnowledgeNotCovered("未指定知识点，无法出题")

    client = get_llm_client()
    names = sorted({spec["name"] for spec in specs})
    queries: dict[int, list[str]] = {}
    llm_queries: dict[str, list[str]] = {}

    try:
        prompt = registry.render(
            "question_plan", course_name=ctx.course_name or "本课程", kp_name=names[0]
        )
        data, _ = await client.chat_json(
            "question_plan",
            [{"role": "user", "content": prompt}],
            meta={"kp_names": names},
            prompt_ver=settings.PROMPT_VERSION,
        )
        llm_queries = data.get("queries") or {}
    except Exception as exc:  # 检索式扩写失败不影响主流程
        logger.warning("plan_llm_failed", error=str(exc))

    for spec in specs:
        name = spec["name"]
        base = llm_queries.get(name) if isinstance(llm_queries, dict) else None
        if not base:
            base = [name, f"{name} 定义 原理", f"{name} 过程 步骤"]
        queries.setdefault(spec["kp_id"], [])
        for q in base[:3]:
            if q not in queries[spec["kp_id"]]:
                queries[spec["kp_id"]].append(q)
    return {"queries": queries}


async def retrieve_node(state: dict[str, Any]) -> dict[str, Any]:
    """按知识点检索；最高相关度低于阈值 → 记 warning 并跳过该知识点（无据不出题）。"""
    ctx: AgentContext = state["_ctx"]
    queries = state.get("queries") or {}
    doc_ids = state.get("doc_ids")
    retrieval_map: dict[int, list[dict[str, Any]]] = {}
    warnings: list[str] = []

    for spec in state.get("kp_specs") or []:
        kp_id = spec["kp_id"]
        best: dict[int, RetrievedChunk] = {}
        for query in queries.get(kp_id, [spec["name"]])[:3]:
            # 这里不逐条 query 重排：交叉编码器在 CPU 上约 60ms/对，19 个知识点 × 3 条 query
            # 会累积到分钟级；改为每个知识点只对"合并后的候选集"重排一次（见下方）
            # 也不做查询改写：这些 query 由 LLM 针对知识点生成（plan 节点），本身就是术语化
            # 检索式，等于已经改写过一遍；再改是重复劳动，且会多消耗 19×3 次 LLM 调用。
            hits = await retrieve(
                ctx.session,
                ctx.course_id,
                query,
                top_k=5,
                doc_ids=doc_ids,
                use_rerank=False,
                use_rewrite=False,
                use_cache=True,
            )
            for hit in hits:
                prev = best.get(hit.chunk_id)
                if prev is None or hit.relevance > prev.relevance:
                    best[hit.chunk_id] = hit
        merged = list(best.values())
        reranked = False
        if merged and rerank.backend_name() != "off":
            merged = await rerank.apply_rerank(spec["name"], merged, 5)
            reranked = True
            for hit in merged:
                best[hit.chunk_id] = hit
        # 重排返回的顺序就是最终顺序，不能再按 relevance 排一遍（否则重排白做）
        ordered = (merged if reranked else sorted(merged, key=lambda c: -c.relevance))[:5]
        top = ordered[0] if ordered else None
        # 门禁看"候选集里最强的证据有多强"，不看它在重排后的位置：
        # 重排会把语义最贴切的片段提到第一，其融合相关度可能反而低于另一位候选，
        # 若按位置判定会把"其实有依据"的查询误拒（实测 2/13）。
        best_relevance = max((c.relevance for c in ordered), default=0.0)
        off_syllabus = (
            top is not None
            and top.unknown_ratio >= settings.MAX_UNKNOWN_TERM_RATIO
            and best_relevance < settings.OFF_SYLLABUS_RELEVANCE_FLOOR
        )
        if top is None or best_relevance < settings.MIN_RETRIEVE_SCORE or off_syllabus:
            reason = (
                f"约 {top.unknown_ratio:.0%} 的查询词在课件中不存在且相关度仅 {best_relevance:.2f}，"
                "判为考纲外"
                if off_syllabus and top is not None
                else f"最高相关度 {best_relevance:.2f}"
            )
            warnings.append(
                f"知识点「{spec['name']}」在知识库中检索不到足够依据（{reason}），已跳过"
            )
            continue
        ctx.remember(ordered)
        retrieval_map[kp_id] = [c.to_dict() for c in ordered]

    if not retrieval_map:
        raise KnowledgeNotCovered()
    return {"retrieval_map": retrieval_map, "warnings": warnings}


async def draft(state: dict[str, Any]) -> dict[str, Any]:
    """每个知识点 × 题型并发调用一次 LLM（并发度由客户端 Semaphore 控制）。"""
    ctx: AgentContext = state["_ctx"]
    client = get_llm_client()
    score = float(state.get("score_per_question") or 5)
    tasks = []
    metas = []

    for spec in state.get("kp_specs") or []:
        chunks = _chunks_for(state, spec["kp_id"])
        if not chunks:
            continue
        difficulty = int(spec.get("difficulty") or 3)
        qtype = spec.get("type", "single")
        prompt = registry.render(
            "question_gen",
            course_name=ctx.course_name or "本课程",
            count=spec.get("count", 1),
            type_label=TYPE_LABEL.get(qtype, "单选题"),
            difficulty_label=DIFFICULTY_LABEL.get(difficulty, "中等"),
            difficulty=difficulty,
            kp_name=spec.get("name", ""),
            option_count=4,
            option_count_minus_one=3,
            score=round(score, 2),
            context_block=context_block(chunks),
            kp_id=spec["kp_id"],
        )
        meta = {
            "count": spec.get("count", 1),
            "type": qtype,
            "kp_id": spec["kp_id"],
            "difficulty": difficulty,
            "score": score,
            "course_name": ctx.course_name,
        }
        metas.append(meta)
        tasks.append(
            client.chat_json(
                "question_gen",
                [
                    {"role": "system", "content": "你是严谨的命题教师，只依据给定材料命题，输出严格 JSON。"},
                    {"role": "user", "content": prompt},
                ],
                meta=meta,
                prompt_ver=settings.PROMPT_VERSION,
            )
        )

    if not tasks:
        return {"pending": [], "warnings": ["没有可用于出题的知识点素材"]}

    results = await asyncio.gather(*tasks, return_exceptions=True)
    pending: list[dict[str, Any]] = []
    warnings: list[str] = []
    for meta, res in zip(metas, results, strict=False):
        if isinstance(res, BaseException):
            warnings.append(f"知识点 {meta['kp_id']} 出题失败：{res}")
            continue
        data, _ = res
        items = data.get("questions") or data.get("data") or []
        if isinstance(items, dict):
            items = [items]
        for item in items:
            if isinstance(item, dict):
                item.setdefault("kp_ids", [meta["kp_id"]])
                item.setdefault("type", meta["type"])
                item.setdefault("difficulty", meta["difficulty"])
                pending.append(item)
        if not items:
            warnings.append(f"知识点 {meta['kp_id']} 未返回题目（模型可能判定材料不足）")
    return {"pending": pending, "warnings": warnings}


async def validate_schema(state: dict[str, Any]) -> dict[str, Any]:
    valid, invalid = validate_drafts(
        state.get("pending") or [], float(state.get("score_per_question") or 5)
    )
    return {"to_verify": valid, "invalid": invalid, "pending": []}


async def verify_citation(state: dict[str, Any]) -> dict[str, Any]:
    ctx: AgentContext = state["_ctx"]
    good: list[dict[str, Any]] = []
    bad: list[dict[str, Any]] = []
    for idx, draft in enumerate(state.get("to_verify") or [], start=1):
        outcome = verify_refs(draft.get("source_refs") or [], ctx.retrieved)
        if not outcome.ok:
            bad.append({"index": idx, "raw": draft, "reason": outcome.reason})
            continue
        draft["source_refs"] = outcome.refs
        draft["_quality"] = outcome.to_quality() | {"fix_count": outcome.fix_count}
        good.append(draft)
    return {"drafts": good, "invalid": bad, "to_verify": []}


async def repair(state: dict[str, Any]) -> dict[str, Any]:
    """把失败原因结构化回灌 prompt，重新命题（temperature 由客户端按 scene 降低）。"""
    ctx: AgentContext = state["_ctx"]
    client = get_llm_client()
    invalid = state.get("invalid") or []
    round_no = int(state.get("repair_round") or 0) + 1
    if not invalid:
        return {"repair_round": round_no}

    reason_lines = []
    for item in invalid[:5]:
        raw = item.get("raw") or {}
        reason_lines.append(
            f"- 第 {item.get('index')} 题（{raw.get('type', '未知')}）：{item.get('reason')}"
        )
    kp_id = None
    for draft in invalid:
        kps = (draft.get("raw") or {}).get("kp_ids") or []
        if kps:
            kp_id = int(kps[0])
            break
    if kp_id is None:
        specs = state.get("kp_specs") or []
        kp_id = specs[0]["kp_id"] if specs else 0
    chunks = _chunks_for(state, kp_id)
    if not chunks:
        return {"repair_round": round_no, "invalid": [], "warnings": ["修复轮缺少原文依据，放弃本批题目"]}

    spec = next((s for s in state.get("kp_specs") or [] if s["kp_id"] == kp_id), None) or {}
    prompt = registry.render(
        "question_gen",
        course_name=ctx.course_name or "本课程",
        count=len(invalid),
        type_label=TYPE_LABEL.get(spec.get("type", "single"), "单选题"),
        difficulty_label=DIFFICULTY_LABEL.get(int(spec.get("difficulty", 3)), "中等"),
        difficulty=int(spec.get("difficulty", 3)),
        kp_name=spec.get("name", "相关知识点"),
        option_count=4,
        option_count_minus_one=3,
        score=round(float(state.get("score_per_question") or 5), 2),
        context_block=context_block(chunks),
        kp_id=kp_id,
    )
    user_content = (
        "你上一轮生成的题目未通过校验，失败原因如下：\n" + "\n".join(reason_lines)
        + "\n\n请严格按失败原因重写这些题目。特别注意：quote 必须是原文逐字连续片段，"
        "chunk_id 必须取自参考资料。\n\n" + prompt
    )
    meta = {
        "count": len(invalid),
        "type": spec.get("type", "single"),
        "kp_id": kp_id,
        "difficulty": int(spec.get("difficulty", 3)),
        "score": float(state.get("score_per_question") or 5),
        "course_name": ctx.course_name,
    }
    data, _ = await client.chat_json(
        "question_gen",
        [{"role": "user", "content": user_content}],
        temperature=0.2,
        meta=meta,
        prompt_ver=settings.PROMPT_VERSION,
    )
    items = data.get("questions") or []
    return {"pending": [i for i in items if isinstance(i, dict)], "invalid": [],
            "repair_round": round_no}


async def score_quality(state: dict[str, Any]) -> dict[str, Any]:
    """计算 quality 指标；主观题/高难题做「答案-证据支撑」第三关自检。"""
    ctx: AgentContext = state["_ctx"]
    client = get_llm_client()
    drafts = state.get("drafts") or []
    warnings: list[str] = []

    for draft in drafts:
        refs = draft.get("source_refs") or []
        coverage = citation_coverage(refs)
        quality = draft.pop("_quality", {}) or {}
        quality.update(
            {
                "citation_ok": True,
                "citation_fix_count": int(quality.get("citation_fix_count", 0)),
                "citation_coverage": coverage,
                "stem_len": len(draft.get("stem", "")),
            }
        )
        if draft.get("type") in ("short", "essay") or int(draft.get("difficulty", 3)) >= 4:
            chunk = ctx.retrieved.get(int(refs[0]["chunk_id"])) if refs else None
            if chunk:
                prompt = registry.render(
                    "question_support",
                    stem=draft.get("stem", ""),
                    answer=str(draft.get("answer", ""))[:500],
                    quote=str(refs[0].get("quote", ""))[:300],
                )
                try:
                    data, _ = await client.chat_json(
                        "question_support",
                        [{"role": "user", "content": prompt}],
                        prompt_ver=settings.PROMPT_VERSION,
                    )
                    supported = bool(data.get("supported", True))
                    quality["answer_supported"] = supported
                    if not supported:
                        quality["citation_ok"] = False
                        warnings.append(
                            f"题目「{draft.get('stem', '')[:20]}…」的答案未被原文支撑，已标记为待人工复核"
                        )
                except Exception as exc:
                    quality["answer_supported"] = None
                    warnings.append(f"答案支撑校验失败：{exc}")
        draft["quality"] = quality

    return {"final_questions": drafts, "warnings": warnings}


def _after_validate(state: dict[str, Any]) -> str:
    if state.get("to_verify"):
        return "verify"
    if state.get("invalid") and int(state.get("repair_round") or 0) < settings.MAX_QUESTION_REPAIR_ROUNDS:
        return "repair"
    return "drop"


def _after_verify(state: dict[str, Any]) -> str:
    if state.get("invalid") and int(state.get("repair_round") or 0) < settings.MAX_QUESTION_REPAIR_ROUNDS:
        return "repair"
    if state.get("drafts"):
        return "quality"
    return "drop"


async def drop(state: dict[str, Any]) -> dict[str, Any]:
    reason = "；".join({item.get("reason", "") for item in (state.get("invalid") or [])})[:200]
    return {
        "final_questions": state.get("drafts") or [],
        "warnings": [f"本批题目部分被丢弃：{reason}"] if reason else [],
    }


def build_graph() -> CompiledGraph:
    graph = StateGraph(QuestionGenState)
    graph.add_node("plan", plan)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("draft", draft)
    graph.add_node("validate_schema", validate_schema)
    graph.add_node("verify_citation", verify_citation)
    graph.add_node("repair", repair)
    graph.add_node("score_quality", score_quality)
    graph.add_node("drop", drop)

    graph.add_edge("plan", "retrieve")
    graph.add_edge("retrieve", "draft")
    graph.add_edge("draft", "validate_schema")
    graph.add_conditional_edges(
        "validate_schema", _after_validate,
        {"verify": "verify_citation", "repair": "repair", "drop": "drop"},
    )
    graph.add_conditional_edges(
        "verify_citation", _after_verify,
        {"repair": "repair", "quality": "score_quality", "drop": "drop"},
    )
    graph.add_edge("repair", "validate_schema")
    graph.add_edge("score_quality", END)
    graph.add_edge("drop", END)
    graph.set_entry_point("plan")
    return graph.compile()


# 图编译一次、全局复用（计划书 9.6 性能要求：禁止每请求重建图）
QUESTION_GRAPH: CompiledGraph = build_graph()
