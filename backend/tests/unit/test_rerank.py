"""重排单元测试：降级路径与打分的正确性。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.rag import rerank


def _items(n: int = 3):
    return [
        SimpleNamespace(chunk_id=i, content=f"片段内容 {i}", relevance=0.1 * (n - i))
        for i in range(1, n + 1)
    ]


@pytest.mark.asyncio
async def test_noop_reranker_keeps_order_and_truncates():
    items = _items(3)
    out = await rerank.NoopReranker().rerank("q", items, 2)
    assert [i.chunk_id for i in out] == [1, 2]
    # 未重排时不写 rerank_score，避免下游把 0 当成"打分为 0"
    assert all(getattr(item, "rerank_score", None) is None for item in items)


def test_get_reranker_returns_noop_when_off(monkeypatch):
    monkeypatch.setattr(rerank.settings, "RERANK_BACKEND", "off")
    rerank.reset_reranker()
    assert isinstance(rerank.get_reranker(), rerank.NoopReranker)


def test_unknown_backend_falls_back_to_noop(monkeypatch):
    monkeypatch.setattr(rerank.settings, "RERANK_BACKEND", "not-a-backend")
    rerank.reset_reranker()
    assert isinstance(rerank.get_reranker(), rerank.NoopReranker)
    rerank.reset_reranker()


@pytest.mark.asyncio
async def test_llm_reranker_sorts_by_score(monkeypatch):
    async def fake_chat_json(*_args, **_kwargs):
        # 故意把第 3 个片段评为最高分；真实签名返回 (dict, LLMResult)
        return (
            {"scores": [{"id": 1, "score": 0.2}, {"id": 2, "score": 0.5}, {"id": 3, "score": 0.9}]},
            SimpleNamespace(text=""),
        )

    monkeypatch.setattr("app.agents.llm.get_llm_client", lambda: SimpleNamespace(chat_json=fake_chat_json))
    items = _items(3)
    out = await rerank.LLMReranker().rerank("查询", items, 2)
    assert [i.chunk_id for i in out] == [3, 2]
    assert out[0].rerank_score == pytest.approx(0.9)
    # 重排分不参与 relevance：否则无关片段的 0.5 基线分会让门禁全部放行
    assert out[0].relevance == pytest.approx(0.0)  # 原始相关性未被重排分污染


@pytest.mark.asyncio
async def test_llm_reranker_falls_back_on_failure(monkeypatch):
    async def boom(*_args, **_kwargs):
        raise RuntimeError("llm down")

    monkeypatch.setattr("app.agents.llm.get_llm_client", lambda: SimpleNamespace(chat_json=boom))
    items = _items(3)
    out = await rerank.LLMReranker().rerank("查询", items, 2)
    assert [i.chunk_id for i in out] == [1, 2]  # 保持原顺序
    assert all(getattr(item, "rerank_score", None) is None for item in items)


@pytest.mark.asyncio
async def test_apply_rerank_swallows_errors(monkeypatch):
    class Broken(rerank.BaseReranker):
        backend = "broken"

        async def rerank(self, query, items, top_k):
            raise RuntimeError("model exploded")

    monkeypatch.setattr(rerank, "get_reranker", lambda: Broken())
    items = _items(3)
    out = await rerank.apply_rerank("查询", items, 2)
    assert [i.chunk_id for i in out] == [1, 2]
