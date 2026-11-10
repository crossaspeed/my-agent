"""最小状态图运行时（LangGraph `StateGraph` 的兼容子集）。

为什么自带实现：答辩/CI 环境可能无法安装 langgraph，本模块保证「克隆即跑」。
API 与 LangGraph 对齐（add_node / add_edge / add_conditional_edges / compile /
invoke / reducers），若安装了 langgraph 可平滑替换为官方实现，业务图代码无需改动。
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, get_args, get_origin, get_type_hints

from app.core.exceptions import AgentError

END = "__end__"
START = "__start__"

NodeFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]] | dict[str, Any]]
RouterFn = Callable[[dict[str, Any]], Awaitable[str] | str]


def _collect_reducers(schema: type) -> dict[str, Callable[[Any, Any], Any]]:
    reducers: dict[str, Callable[[Any, Any], Any]] = {}
    try:
        hints = get_type_hints(schema, include_extras=True)
    except Exception:  # pragma: no cover - 类型注解异常时退化为覆盖语义
        return reducers
    for key, hint in hints.items():
        if get_origin(hint) is Annotated:
            for meta in get_args(hint)[1:]:
                if callable(meta):
                    reducers[key] = meta
                    break
    return reducers


class CompiledGraph:
    def __init__(
        self,
        nodes: dict[str, NodeFn],
        edges: dict[str, str],
        conditional: dict[str, tuple[RouterFn, dict[str, str]]],
        reducers: dict[str, Callable[[Any, Any], Any]],
        entry: str,
        max_steps: int = 64,
    ) -> None:
        self.nodes = nodes
        self.edges = edges
        self.conditional = conditional
        self.reducers = reducers
        self.entry = entry
        self.max_steps = max_steps

    def _merge(self, state: dict[str, Any], update: dict[str, Any] | None) -> None:
        if not update:
            return
        for key, value in update.items():
            reducer = self.reducers.get(key)
            if reducer is not None and key in state:
                state[key] = reducer(state[key], value)
            else:
                state[key] = value

    async def invoke(self, state: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
        current = self.entry
        steps = 0
        trace: list[str] = []
        while current != END:
            steps += 1
            if steps > self.max_steps:
                raise AgentError(current, f"状态图执行超过最大步数 {self.max_steps}（疑似死循环）")
            node = self.nodes.get(current)
            if node is None:
                raise AgentError(current, "节点未注册")
            trace.append(current)
            try:
                result = node(state)
                if inspect.isawaitable(result):
                    result = await result
            except AgentError:
                raise
            except Exception as exc:  # 统一包装，便于定位节点
                raise AgentError(current, str(exc)) from exc
            self._merge(state, result)

            if current in self.conditional:
                router, mapping = self.conditional[current]
                key = router(state)
                if inspect.isawaitable(key):
                    key = await key
                nxt = mapping.get(key, END)
            else:
                nxt = self.edges.get(current, END)
            current = nxt

        state.setdefault("trace", trace)
        return state


class StateGraph:
    def __init__(self, state_schema: Any) -> None:
        self.schema = state_schema
        self._nodes: dict[str, NodeFn] = {}
        self._edges: dict[str, str] = {}
        self._conditional: dict[str, tuple[RouterFn, dict[str, str]]] = {}
        self._entry: str | None = None

    def add_node(self, name: str, fn: NodeFn) -> StateGraph:
        self._nodes[name] = fn
        return self

    def add_edge(self, start: str, end: str) -> StateGraph:
        if start == START:
            self._entry = end
        else:
            self._edges[start] = end
        return self

    def add_conditional_edges(
        self, node: str, router: RouterFn, mapping: dict[str, str]
    ) -> StateGraph:
        self._conditional[node] = (router, mapping)
        return self

    def set_entry_point(self, name: str) -> StateGraph:
        self._entry = name
        return self

    def compile(self) -> CompiledGraph:
        if not self._entry:
            raise AgentError("compile", "未设置入口节点（add_edge(START, ...)）")
        return CompiledGraph(
            nodes=self._nodes,
            edges=self._edges,
            conditional=self._conditional,
            reducers=_collect_reducers(self.schema),
            entry=self._entry,
        )
