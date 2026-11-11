"""检索能力基准测试：固定查询集 + 标注 gold chunk，输出可对比的原始信号。

用法（容器内）：
    python /app/scripts/retrieval_bench.py /tmp/bench.json

设计说明：
- 只记录**原始信号**（top3 chunk、relevance、coverage、unknown_ratio、是否拒答），
  便于不同版本（hash / bge-m3、有无门禁）在同一口径下复算指标，避免脚本本身影响结论。
- 拒答判定复刻生产逻辑：
    decision = relevance >= MIN_RETRIEVE_SCORE and unknown_ratio < MAX_UNKNOWN_TERM_RATIO
  未实现门禁的版本 unknown_ratio 记为 None，判定退化为旧规则（只看 relevance）。
"""

from __future__ import annotations

import asyncio
import json
import statistics
import sys

from app.core.config import settings
from app.db.base import AsyncSessionLocal
from app.rag.embedder import get_embedder
from app.rag.retriever import retrieve

COURSE_ID = 1
TOP_K = 5

# (类别, 查询, gold chunk id 列表)；gold 为空表示"语料中确实没有答案，应拒答"
CASES: list[tuple[str, str, list[int]]] = [
    ("字面", "TCP 三次握手的 SYN 和 ACK 标志位分别起什么作用", [1, 2]),
    ("字面", "慢开始门限 ssthresh 是怎么变化的", [3]),
    ("字面", "滑动窗口 rwnd 如何实现流量控制", [3]),
    ("字面", "RIP 与 OSPF 的区别是什么", [6]),
    ("字面", "NAT 与 NAPT 的作用", [6]),
    ("字面", "DES 和 AES 属于对称加密算法吗", [7]),
    ("口语", "两台主机开始对话之前为什么要先对暗号", [1, 2]),
    ("口语", "网络为什么会堵车", [3]),
    ("口语", "接收方处理不过来数据怎么办", [3]),
    ("口语", "地址不够用，怎么让很多机器共用一个公网地址", [6]),
    ("口语", "怎么证明一份文件确实是某人发出的", [7]),
    ("跨语言", "three-way handshake", [1, 2]),
    ("跨语言", "congestion control and slow start", [3]),
    ("领域外", "数据库 B+ 树索引的分裂过程", []),
    ("领域外", "红烧肉的正宗做法", []),
    ("领域外", "矩阵特征值分解的几何意义", []),
]


async def main(out_path: str) -> None:
    embedder = get_embedder()
    rows = []
    async with AsyncSessionLocal() as session:
        for category, query, gold in CASES:
            hits = await retrieve(session, COURSE_ID, query, top_k=TOP_K, use_cache=False)
            top = hits[:3]
            top1 = top[0] if top else None
            # 门禁口径与 question_graph 一致：先按 relevance 取最强证据，再判是否可用
            gate = max(hits, key=lambda h: h.relevance) if hits else None
            unknown_ratio = getattr(gate, "unknown_ratio", None)
            relevance = float(gate.relevance) if gate else 0.0

            off_syllabus = (
                unknown_ratio is not None
                and unknown_ratio >= settings.MAX_UNKNOWN_TERM_RATIO
                and relevance < settings.OFF_SYLLABUS_RELEVANCE_FLOOR
            )
            accepted = gate is not None and relevance >= settings.MIN_RETRIEVE_SCORE and (
                not off_syllabus
            )
            hit1 = bool(top1 and top1.chunk_id in gold)
            hit3 = any(h.chunk_id in gold for h in top)

            rows.append(
                {
                    "category": category,
                    "query": query,
                    "gold": gold,
                    "top": [
                        {
                            "chunk_id": h.chunk_id,
                            "heading": h.heading_path,
                            "score": round(float(h.score), 4),
                            "relevance": round(float(h.relevance), 4),
                            "coverage": round(float(getattr(h, "coverage", 0.0) or 0.0), 4),
                            "source": h.source,
                        }
                        for h in top
                    ],
                    "gate_chunk": gate.chunk_id if gate else None,
                    "relevance_top1": round(relevance, 4),
                    "coverage_top1": round(float(getattr(gate, "coverage", 0.0) or 0.0), 4)
                    if gate
                    else 0.0,
                    "unknown_ratio": None if unknown_ratio is None else round(unknown_ratio, 4),
                    "accepted": accepted,
                    "hit@1": hit1,
                    "hit@3": hit3,
                }
            )

    in_scope = [r for r in rows if r["gold"]]
    out_scope = [r for r in rows if not r["gold"]]
    metrics = {
        "embedder": type(embedder).__name__,
        "dim": embedder.dim,
        "course_chunks": None,
        "n_total": len(rows),
        "n_in_scope": len(in_scope),
        "n_out_scope": len(out_scope),
        "hit@1": round(sum(r["hit@1"] for r in in_scope) / len(in_scope), 4),
        "hit@3": round(sum(r["hit@3"] for r in in_scope) / len(in_scope), 4),
        # 语料内有答案却被拒答（过度拒答），越低越好
        "false_reject_rate": round(
            sum(1 for r in in_scope if not r["accepted"]) / len(in_scope), 4
        ),
        # 语料内没有答案却照常作答（幻觉风险），越低越好
        "false_accept_rate": round(
            sum(1 for r in out_scope if r["accepted"]) / len(out_scope), 4
        ),
        # 静默错误：有答案、没拒答、但 top1 不是 gold —— 最危险的一类
        "silent_error": sum(
            1 for r in in_scope if r["accepted"] and not r["hit@1"]
        ),
        "relevance_top1_median": round(statistics.median([r["relevance_top1"] for r in rows]), 4),
    }

    payload = {"metrics": metrics, "rows": rows}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/bench.json"))
