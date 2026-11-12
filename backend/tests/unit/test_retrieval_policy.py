"""场景化检索策略的护栏测试。

三个检索入口的 query 来源不同，对「重排 / 查询改写」的取舍也不同，
这是有实测依据的产品决策（见 docs/experiments/metrics-current.md 第 9 节），
不是随手写的默认值。这里用源码断言把它固定下来，避免后续重构时被误删或误开。

| 入口 | query 来源 | 重排 | 改写 | 依据 |
|---|---|---|---|---|
| 导学·首次 | 知识点名称拼接（教材术语） | 关 | 关 | 已是术语，改写是重复劳动；SSE 首字延迟优先 |
| 导学·追问 | 学生原话 + 题干（口语/跨语言） | 关 | **开** | 唯一的学生自由语言入口，实测口语 Hit@3 0.867→1.000 |
| 出题 | LLM 生成的检索式（已术语化） | 关（改为按知识点合并后重排） | 关 | 检索式本身是改写产物，再改是重复调用 |
| 阅卷 | 题干 + 解析（字面类） | 开 | 关 | 实测字面类改写 relevance 均值 -0.007，属净损失 |
"""

from __future__ import annotations

import inspect
import re

from app.agents import grader_graph, question_graph, tutor_graph


def _retrieve_calls(module: object) -> list[str]:
    """取出模块里所有 retrieve(...) 调用的源码片段（含多行参数）。"""
    src = inspect.getsource(module)
    return re.findall(r"retrieve\((?:[^()]|\([^()]*\))*?\)", src, flags=re.S)


def _param(call: str, name: str) -> bool | None:
    match = re.search(rf"{name}\s*=\s*(True|False)", call)
    return None if match is None else match.group(1) == "True"


def test_tutor_rewrites_only_on_followup():
    """导学有两个检索点：首次（知识点名）不改写，追问（学生原话）必须改写。"""
    calls = _retrieve_calls(tutor_graph)
    assert len(calls) == 2, f"导学应有 2 个检索点，实际 {len(calls)}"
    # 源码顺序：retrieve_node（首次）在前，retrieve_followup（追问）在后
    assert _param(calls[0], "use_rewrite") is False
    assert _param(calls[1], "use_rewrite") is True
    # 两个分支都不开重排：SSE 首字延迟优先
    assert all(_param(c, "use_rerank") is False for c in calls)


def test_question_graph_never_rewrites():
    """出题的检索式由 LLM 生成，已是术语化产物；再改写等于把同一件事做两遍。"""
    calls = _retrieve_calls(question_graph)
    assert calls, "出题应有检索调用"
    assert all(_param(c, "use_rewrite") is False for c in calls)


def test_grader_reranks_but_never_rewrites():
    """阅卷的 query 是题干+解析（字面类），改写实测使 relevance 微降。"""
    calls = _retrieve_calls(grader_graph)
    assert calls, "阅卷应有检索调用"
    assert all(_param(c, "use_rewrite") is False for c in calls)
    assert any(_param(c, "use_rerank") is True for c in calls)
