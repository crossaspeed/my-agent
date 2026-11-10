"""检索与融合单元测试。"""

from __future__ import annotations

from app.rag.bm25_index import tokenize
from app.rag.retriever import rrf_fuse


def test_rrf_prefers_shared_items():
    dense = [1, 2, 3]
    sparse = [3, 1, 4]
    fused = rrf_fuse(dense, sparse, k=60)
    assert fused[0][0] == 1  # 1 与 3 都命中两次，1 的排名更好
    assert fused[0][1] > fused[-1][1]


def test_rrf_scores_positive():
    fused = rrf_fuse([10], [20], k=60)
    assert all(score > 0 for _, score in fused)
    assert len(fused) == 2


def test_tokenize_chinese_terms():
    tokens = tokenize("TCP 三次握手与滑动窗口")
    assert "三次" in tokens or "握手" in tokens
    assert all(t.strip() for t in tokens)


def test_tokenize_drops_stopwords():
    tokens = tokenize("这是 一个 的 测试")
    assert "的" not in tokens


def test_difficulty_pick():
    from app.agents.orchestrator import _pick_difficulty

    assert _pick_difficulty(5, {"easy": 0.2, "medium": 0.6, "hard": 0.2}) == 3
    assert _pick_difficulty(1, {"easy": 1.0, "medium": 0.0, "hard": 0.0}) == 2


def test_build_kp_specs_distribution():
    from app.agents.orchestrator import build_kp_specs

    specs = build_kp_specs(
        kp_ids=[1, 2],
        kp_names={1: "三次握手", 2: "拥塞控制"},
        types={"single": 3, "short": 1},
        difficulty={"easy": 0.2, "medium": 0.6, "hard": 0.2},
        score_per_question=5,
    )
    total = sum(s["count"] for s in specs)
    assert total == 4
    assert {s["kp_id"] for s in specs} == {1, 2}
