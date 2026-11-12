"""查询改写：成功路径、失败降级、缓存。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.rag import query_rewrite


def _fake_client(payload: dict, calls: list[str]):
    class Fake:
        async def chat_json(self, scene, messages, **kwargs):  # noqa: ANN001
            calls.append(messages[-1]["content"])
            return payload, SimpleNamespace(latency_ms=12, text="")

    return Fake()


def test_rewrite_returns_rewritten(monkeypatch):
    query_rewrite.clear_cache()
    calls: list[str] = []
    monkeypatch.setattr(
        query_rewrite,
        "_get_client",
        lambda: _fake_client({"rewritten": "TCP 拥塞控制 网络过载 成因"}, calls),
    )
    text, meta = asyncio.run(query_rewrite.rewrite_query("网络为什么会堵车"))
    assert text == "TCP 拥塞控制 网络过载 成因"
    assert meta["rewritten"] is True
    assert len(calls) == 1


def test_rewrite_failure_falls_back(monkeypatch):
    query_rewrite.clear_cache()

    class Boom:
        async def chat_json(self, *a, **kw):  # noqa: ANN002, ANN003
            raise RuntimeError("llm down")

    monkeypatch.setattr(query_rewrite, "_get_client", lambda: Boom())
    text, meta = asyncio.run(query_rewrite.rewrite_query("网络为什么会堵车"))
    assert text == "网络为什么会堵车"           # 原样返回，检索不受影响
    assert meta["rewritten"] is False
    assert "llm down" in meta["reason"] or meta["reason"]


def test_rewrite_rejects_empty_output(monkeypatch):
    query_rewrite.clear_cache()
    calls: list[str] = []
    monkeypatch.setattr(
        query_rewrite, "_get_client", lambda: _fake_client({"rewritten": "  "}, calls)
    )
    text, meta = asyncio.run(query_rewrite.rewrite_query("堵车"))
    assert text == "堵车"
    assert meta["rewritten"] is False


def test_rewrite_cache_hits(monkeypatch):
    query_rewrite.clear_cache()
    calls: list[str] = []
    monkeypatch.setattr(
        query_rewrite, "_get_client",
        lambda: _fake_client({"rewritten": "三报文握手 同步序号"}, calls),
    )
    asyncio.run(query_rewrite.rewrite_query("为什么要先对暗号"))
    text, meta = asyncio.run(query_rewrite.rewrite_query("为什么要先对暗号"))
    assert text == "三报文握手 同步序号"
    assert meta.get("cached") is True
    assert len(calls) == 1, "同一问题不应重复调用 LLM"


def test_rewrite_empty_query():
    query_rewrite.clear_cache()
    text, meta = asyncio.run(query_rewrite.rewrite_query("   "))
    assert text == "   "
    assert meta["rewritten"] is False


@pytest.mark.parametrize("bad", ["", None])
def test_rewrite_handles_falsy(bad):
    query_rewrite.clear_cache()
    out, meta = asyncio.run(query_rewrite.rewrite_query(bad))  # type: ignore[arg-type]
    assert meta["rewritten"] is False
