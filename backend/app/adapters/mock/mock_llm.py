"""离线 Mock LLM（计划书 17.2）。

设计要点：Mock 不是「假数据」，而是**基于本次真实检索到的 chunk 生成**，因此
chunk_id、quote 都能通过引用校验，全链路（出题→作答→阅卷→导学）在 LLM_PROVIDER=mock
下可完整跑通，这是 CI 与答辩离线演示的基础。
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.agents.prompts.registry import PROMPT_DIR

CHUNK_BLOCK = re.compile(
    r"\[CHUNK\s+(\d+)\s*\|([^\]]*)\]\s*\n(.*?)(?=\n\[CHUNK\s+\d+\s*\||\n# |\Z)", re.DOTALL
)
SENTENCE = re.compile(r"(?<=[。！？；!?;])\s*")
ERROR_TAGS = ["概念混淆", "遗漏前提", "表述不全", "张冠李戴", "逻辑错误", "计算失误", "未作答"]


def _split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in SENTENCE.split(text.replace("\n", " ")) if p.strip()]
    return [p for p in parts if len(p) >= 8]


def _mutate(sentence: str) -> str:
    """制造一个有迷惑性的错误选项：数字 +1 / 否定翻转 / 偷换主体。"""
    digits = re.findall(r"\d+", sentence)
    if digits:
        for d in digits:
            new = str(int(d) + 1)
            return sentence.replace(d, new, 1)
    for src, dst in (("必须", "无需"), ("大于", "小于"), ("可以", "不能"), ("先", "后")):
        if src in sentence:
            return sentence.replace(src, dst, 1)
    return sentence.replace("是", "不是", 1) if "是" in sentence else sentence + "（此说法有误）"


class MockLLM:
    """按 scene 路由的规则式生成器。"""

    def __init__(self) -> None:
        self.fixture_dir = PROMPT_DIR.parent.parent / "adapters" / "mock" / "fixtures"

    # ---------------- 入口 ----------------
    async def reply(self, scene: str, messages: list[dict[str, str]],
                    meta: dict[str, Any] | None = None) -> str:
        meta = meta or {}
        user_content = "\n".join(m.get("content", "") for m in messages if m.get("role") == "user")
        if scene == "question_plan":
            return self._plan(meta)
        if scene == "question_gen":
            return self._questions(user_content, meta)
        if scene == "question_support":
            return json.dumps(
                {"supported": True, "missing": []}, ensure_ascii=False
            )
        if scene in ("grader_extract", "grader_subjective"):
            return self._grade({**meta, "scene": scene})
        if scene == "tutor":
            return self._tutor(meta)
        return "（Mock 模型未定义该场景的响应）"

    # ---------------- 出题 ----------------
    def _plan(self, meta: dict[str, Any]) -> str:
        names: list[str] = meta.get("kp_names") or []
        queries = {
            name: [name, f"{name} 定义 原理", f"{name} 过程 步骤"] for name in names
        }
        return json.dumps({"queries": queries}, ensure_ascii=False)

    def _questions(self, prompt: str, meta: dict[str, Any]) -> str:
        chunks: list[tuple[int, str, str]] = []
        for chunk_id, header, content in CHUNK_BLOCK.findall(prompt):
            chunks.append((int(chunk_id), header.strip(), content.strip()))
        if not chunks:
            return json.dumps({"questions": []}, ensure_ascii=False)

        count = int(meta.get("count", 1))
        qtype = str(meta.get("type", "single"))
        kp_id = meta.get("kp_id")
        difficulty = int(meta.get("difficulty", 3))
        score = float(meta.get("score", 5))
        questions: list[dict[str, Any]] = []

        for i in range(count):
            chunk_id, header, content = chunks[i % len(chunks)]
            sentences = _split_sentences(content)
            if not sentences:
                continue
            anchor = sentences[0][:150]
            candidates = sentences[1:] or sentences

            if qtype == "single":
                options = [
                    {"key": "A", "text": anchor[:80]},
                    {"key": "B", "text": _mutate(candidates[0])[:80]},
                    {"key": "C", "text": _mutate(candidates[-1])[:80]},
                    {"key": "D", "text": "题干所述内容与教材结论完全相反"},
                ]
                answer: Any = "A"
                stem = f"依据课程材料，下列关于「{_topic(header, anchor)}」的表述，正确的是？"
            elif qtype == "multiple":
                options = [
                    {"key": "A", "text": anchor[:80]},
                    {"key": "B", "text": candidates[0][:80]},
                    {"key": "C", "text": _mutate(candidates[-1])[:80]},
                    {"key": "D", "text": _mutate(anchor)[:80]},
                ]
                answer = ["A", "B"]
                stem = f"关于「{_topic(header, anchor)}」，下列说法正确的有？"
            elif qtype == "judge":
                wrong = _mutate(anchor)
                stem = f"判断：{wrong[:110]}"
                answer = False
                options = None
            else:  # short / essay
                stem = f"请结合课程材料，说明「{_topic(header, anchor)}」的含义与作用。"
                answer = {"key_points": [candidates[j][:60] for j in range(min(3, len(candidates)))]}
                options = None

            rubric: list[dict[str, Any]] = []
            if qtype in ("short", "essay"):
                per = round(score / 3, 2)
                for j in range(3):
                    point = (candidates[j] if j < len(candidates) else anchor)[:60]
                    rubric.append(
                        {
                            "point": point,
                            "score": per,
                            "keywords": _keywords(point),
                        }
                    )
                rubric[-1]["score"] = round(score - per * 2, 2)

            questions.append(
                {
                    "type": qtype,
                    "stem": stem,
                    "options": options,
                    "answer": answer,
                    "rubric": rubric,
                    "explanation": f"依据课件原文：{anchor[:120]}",
                    "difficulty": difficulty,
                    "kp_ids": [kp_id] if kp_id else [],
                    "source_refs": [{"chunk_id": chunk_id, "quote": anchor[:120]}],
                }
            )
        return json.dumps({"questions": questions}, ensure_ascii=False)

    # ---------------- 阅卷 ----------------
    def _grade(self, meta: dict[str, Any]) -> str:
        rubric: list[dict[str, Any]] = meta.get("rubric") or []
        answer_text: str = str(meta.get("student_answer") or "")
        max_score = float(meta.get("max_score", 0) or 0)
        if meta.get("scene") == "grader_extract" or not rubric:
            points = [p.strip() for p in re.split(r"[。；;\n]", answer_text) if len(p.strip()) > 4]
            return json.dumps(
                {"points": [{"text": p, "span": p} for p in points[:6]]}, ensure_ascii=False
            )

        if not answer_text.strip():
            return json.dumps(
                {
                    "rubric_detail": [
                        {"point": r.get("point", ""), "hit": "miss", "score": 0, "evidence": ""}
                        for r in rubric
                    ],
                    "score": 0,
                    "feedback": "本题未作答。建议先梳理题干涉及的核心概念，再按「定义—机制—易错点」组织答案。",
                    "error_tags": ["未作答"],
                    "confidence": 0.99,
                },
                ensure_ascii=False,
            )

        detail: list[dict[str, Any]] = []
        total = 0.0
        hit_count = 0
        for item in rubric:
            point_score = float(item.get("score", 0) or 0)
            keywords = [str(k) for k in (item.get("keywords") or [])]
            hits = [k for k in keywords if k and k in answer_text]
            if keywords and len(hits) >= max(2, len(keywords) // 2):
                ratio = 1.0
            elif hits or _overlap(item.get("point", ""), answer_text) > 0.45:
                ratio = 0.5
            else:
                ratio = 0.0
            gained = round(point_score * ratio, 2)
            if ratio == 0.5:
                gained = min(gained, round(point_score * 0.5, 2))
            total += gained
            if ratio > 0:
                hit_count += 1
            detail.append(
                {
                    "point": item.get("point", ""),
                    "hit": {1.0: "hit", 0.5: "partial", 0.0: "miss"}[ratio],
                    "score": gained,
                    "evidence": _evidence(answer_text, keywords),
                }
            )
        total = min(round(total, 2), max_score)
        tags = []
        if hit_count == 0:
            tags = ["概念混淆"]
        elif hit_count < len(rubric):
            tags = ["表述不全"]
        feedback = (
            f"你的答案覆盖了 {hit_count}/{len(rubric)} 个评分点，"
            + ("主要得分点已答到，但部分环节描述不完整，建议补齐缺失要点并说明因果。" if hit_count else "核心概念尚未建立，建议回看对应课件段落。")
        )
        return json.dumps(
            {
                "rubric_detail": detail,
                "score": total,
                "feedback": feedback,
                "error_tags": tags,
                "confidence": 0.82 if hit_count else 0.7,
            },
            ensure_ascii=False,
        )

    # ---------------- 导学 ----------------
    def _tutor(self, meta: dict[str, Any]) -> str:
        stem = str(meta.get("stem") or "本题")
        raw_answer = meta.get("student_answer")
        if isinstance(raw_answer, list):
            student_answer = "、".join(str(v) for v in raw_answer)
        elif isinstance(raw_answer, bool):
            student_answer = "正确" if raw_answer else "错误"
        else:
            student_answer = str(raw_answer or "").strip()
        tags = meta.get("error_tags") or []
        refs = meta.get("refs") or []
        followup = meta.get("user_query")
        course = meta.get("course_name") or "本课程"
        snippet = student_answer[:30] if student_answer else "（未作答）"

        if followup:
            return (
                f"你问的是「{followup}」。回到本题的关键：{stem[:40]}…\n\n"
                f"回答这个问题只需要抓住一点——{'、'.join(tags) if tags else '概念边界'}。"
                f"教材里对应的表述是：{meta.get('anchor', '（见引用）')[:60]} [1]\n\n"
                "一句话总结：先把「是什么」和「为什么必须这样」分开记忆，再回到本题的判断条件。"
            )

        lines = [
            f"先定位问题：你的答案写的是「{snippet}」，"
            + (f"这里出现了{'、'.join(tags)}，" if tags else "与题干要求的方向不一致，")
            + "说明关键环节没有落到教材的定义上。",
            "",
            "**先建立直觉**",
            f"把「{stem[:24]}…」想象成一个快递签收流程：只有双方都确认过身份，包裹才不会被错领。 [1]",
            "",
            "**再看机制**",
            "1. 先明确本题涉及的主体与状态；",
            f"2. 再按教材给出的顺序推进：{meta.get('anchor', '（见引用原文）')[:60]} [1]",
            "3. 最后检查边界条件（数量、时序、取值范围）。",
            "",
            "**最后避坑**",
            "常见误区一：把相近概念互换，导致判断方向相反；",
            "误区二：只记住结论而忽略前提条件，遇到改动数值的题目就失效。",
        ]
        if refs:
            lines += ["", f"以上结论依据课件原文（共 {len(refs)} 处引用），可点击下方溯源卡片查看。"]
        lines += ["", f"复习动作：回看《{course}》对应章节原文，重点抄写一遍上述关键句，再重做同类题。"]
        return "\n".join(lines)


def _topic(header: str, anchor: str) -> str:
    if ">" in header:
        return header.split(">")[-1].strip()
    return (anchor[:18] + "…") if len(anchor) > 18 else anchor


def _keywords(point: str) -> list[str]:
    tokens = [t for t in re.split(r"[，,。；;、\s]+", point) if len(t) >= 2]
    if len(tokens) <= 1:
        return [point[:8]] if len(point) >= 2 else [point]
    return tokens[:3]


def _overlap(point: str, answer: str) -> float:
    chars = {c for c in point if "\u4e00" <= c <= "\u9fff"}
    if not chars:
        return 0.0
    hit = sum(1 for c in chars if c in answer)
    return hit / len(chars)


def _evidence(answer_text: str, keywords: list[str]) -> str:
    for kw in keywords:
        if kw and kw in answer_text:
            idx = answer_text.find(kw)
            return answer_text[max(0, idx - 8) : idx + len(kw) + 8]
    return ""
