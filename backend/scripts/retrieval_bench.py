"""检索能力基准测试：固定查询集 + 标注 gold chunk，输出可对比的原始信号。

用法（容器内）：
    # 内置演示用例（课程 1，16 条）
    python -m scripts.retrieval_bench --out /tmp/bench.json

    # 自定义标注集（CSV 需含 category, query, gold 三列；gold 为空表示应拒答）
    python -m scripts.retrieval_bench --cases /tmp/cases.csv --course-id 8 \
        --out /tmp/bench.json [--rerank]

设计说明：
- 只记录**原始信号**（top3 chunk、relevance、coverage、unknown_ratio、是否拒答），
  便于不同版本（hash / bge-m3、有无门禁）在同一口径下复算指标，避免脚本本身影响结论。
- 拒答判定复刻生产逻辑（`question_graph`）：相关度取候选集最大值，
  启用重排时门禁看重排后的第一条；未登录词率与相关度**联判**才算考纲外。
- `silent_error` 与 `scripts/bench_report.py` 统一为「放行但 top3 无正确答案」。
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import statistics
import time
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.db.base import AsyncSessionLocal
from app.rag import query_rewrite
from app.rag.embedder import get_embedder
from app.rag.retriever import retrieve

DEFAULT_COURSE_ID = 1
TOP_K = 5

# 课程 1（演示 md 语料）的内置用例；gold 为空表示"语料中确实没有答案，应拒答"
DEFAULT_CASES: list[tuple[str, str, list[int]]] = [
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


def load_cases(path: str) -> list[tuple[str, str, list[int]]]:
    """从 CSV 读取用例。`gold` 允许 `"398,399"` 或 `398`，空表示应拒答。

    CSV 通常是 Excel 保存的（UTF-8 BOM），必须用 utf-8-sig，否则首列名会带 \\ufeff。
    """
    cases: list[tuple[str, str, list[int]]] = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for lineno, row in enumerate(csv.DictReader(f), start=2):
            query = (row.get("query") or "").strip()
            if not query:
                continue
            raw = (row.get("gold") or "").replace(" ", "")
            gold: list[int] = []
            for part in raw.split(","):
                if not part:
                    continue
                if not part.isdigit():
                    raise ValueError(f"第 {lineno} 行 gold 含非数字项：{part!r}")
                gold.append(int(part))
            cases.append(((row.get("category") or "未分类").strip(), query, gold))
    if not cases:
        raise ValueError(f"用例文件为空或缺少 query 列：{path}")
    return cases


async def run(session: Any, course_id: int, cases: list[tuple[str, str, list[int]]],
              use_rerank: bool,
              use_rewrite: bool = False) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    backend = settings.RERANK_BACKEND.strip().lower()
    rerank_on = bool(use_rerank) and backend not in ("", "off", "none", "0", "false")
    rows: list[dict[str, Any]] = []
    for category, query, gold in cases:
        started = time.perf_counter()
        error: str | None = None
        rewritten: str | None = None
        if use_rewrite and settings.QUERY_REWRITE_ENABLED:
            # 先显式改写一次用于记录（retrieve 内部会命中同一缓存，不会重复调用 LLM）
            rewritten, meta = await query_rewrite.rewrite_query(query)
            if not meta.get("rewritten") or rewritten == query:
                rewritten = None
        try:
            hits = await retrieve(
                session, course_id, query, top_k=TOP_K,
                use_rerank=use_rerank, use_rewrite=use_rewrite, use_cache=False,
            )
        except Exception as exc:  # 单条失败不应中断整批评测
            hits = []
            error = f"{type(exc).__name__}: {exc}"[:200]
        latency_ms = round((time.perf_counter() - started) * 1000)

        top = hits[:3]
        top1 = top[0] if top else None
        # 门禁口径与 question_graph 一致：启用重排时顺序即重排结果，否则按相关度取最强证据
        gate = (hits[0] if rerank_on and hits else
                (max(hits, key=lambda h: h.relevance) if hits else None))
        unknown_ratio = getattr(gate, "unknown_ratio", None)
        # 门禁相关度取候选集最大值，与重排位置无关
        relevance = max((h.relevance for h in hits), default=0.0)

        off_syllabus = (
            unknown_ratio is not None
            and unknown_ratio >= settings.MAX_UNKNOWN_TERM_RATIO
            and relevance < settings.OFF_SYLLABUS_RELEVANCE_FLOOR
        )
        accepted = (
            gate is not None
            and relevance >= settings.MIN_RETRIEVE_SCORE
            and not off_syllabus
        )
        rows.append(
            {
                "category": category,
                "query": query,
                "rewritten": rewritten,
                "gold": gold,
                "latency_ms": latency_ms,
                "top": [
                    {
                        "chunk_id": h.chunk_id,
                        "heading": h.heading_path,
                        "score": round(float(h.score), 4),
                        "relevance": round(float(h.relevance), 4),
                        "coverage": round(float(getattr(h, "coverage", 0.0) or 0.0), 4),
                        "rerank_score": getattr(h, "rerank_score", None),
                        "source": h.source,
                    }
                    for h in top
                ],
                "gate_chunk": gate.chunk_id if gate else None,
                "relevance_top1": round(relevance, 4),
                "unknown_ratio": None if unknown_ratio is None else round(unknown_ratio, 4),
                "accepted": accepted,
                "hit@1": bool(top1 and top1.chunk_id in gold),
                "hit@3": any(h.chunk_id in gold for h in top),
                "error": error,
            }
        )
    metrics = summarize(rows)
    return rows, metrics


def _rate(num: int, den: int) -> float:
    return round(num / den, 4) if den else 0.0


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    in_scope = [r for r in rows if r["gold"]]
    out_scope = [r for r in rows if not r["gold"]]

    def block(rs: list[dict[str, Any]]) -> dict[str, Any]:
        ins = [r for r in rs if r["gold"]]
        outs = [r for r in rs if not r["gold"]]
        return {
            "n": len(rs),
            "n_in_scope": len(ins),
            "n_out_scope": len(outs),
            "hit@1": _rate(sum(r["hit@1"] for r in ins), len(ins)),
            "hit@3": _rate(sum(r["hit@3"] for r in ins), len(ins)),
            "false_reject": _rate(sum(1 for r in ins if not r["accepted"]), len(ins)),
            "false_accept": _rate(sum(1 for r in outs if r["accepted"]), len(outs)),
            # 与 bench_report.py 同口径：放行但证据集里没有正确答案
            "silent_error": sum(1 for r in ins if r["accepted"] and not r["hit@3"]),
            "gate_hit": _rate(sum(1 for r in ins if r["gate_chunk"] in r["gold"]),
                              sum(1 for r in ins if r["gate_chunk"] is not None)),
            "avg_latency_ms": round(statistics.fmean([r["latency_ms"] for r in rs]), 1),
        }

    by_category = {
        cat: block([r for r in rows if r["category"] == cat])
        for cat in sorted({r["category"] for r in rows})
    }
    return {
        "n_total": len(rows),
        "n_in_scope": len(in_scope),
        "n_out_scope": len(out_scope),
        "hit@1": _rate(sum(r["hit@1"] for r in in_scope), len(in_scope)),
        "hit@3": _rate(sum(r["hit@3"] for r in in_scope), len(in_scope)),
        "false_reject_rate": _rate(sum(1 for r in in_scope if not r["accepted"]), len(in_scope)),
        "false_accept_rate": _rate(sum(1 for r in out_scope if r["accepted"]), len(out_scope)),
        "silent_error": sum(1 for r in in_scope if r["accepted"] and not r["hit@3"]),
        "gate_hit": _rate(sum(1 for r in in_scope if r["gate_chunk"] in r["gold"]),
                          sum(1 for r in in_scope if r["gate_chunk"] is not None)),
        "relevance_median": round(statistics.median([r["relevance_top1"] for r in rows]), 4),
        "avg_latency_ms": round(statistics.fmean([r["latency_ms"] for r in rows]), 1),
        "by_category": by_category,
    }


def print_table(metrics: dict[str, Any]) -> None:
    print(f"{'类别':<10}{'n':>4}{'Hit@1':>8}{'Hit@3':>8}{'误拒':>8}"
          f"{'误纳':>8}{'静默':>6}{'门禁':>8}")
    print("-" * 62)
    for cat, m in metrics["by_category"].items():
        print(f"{cat:<10}{m['n']:>4}{m['hit@1']:>8.3f}{m['hit@3']:>8.3f}"
              f"{m['false_reject']:>8.3f}{m['false_accept']:>8.3f}"
              f"{m['silent_error']:>6}{m['gate_hit']:>8.3f}")
    print("-" * 62)
    print(f"{'合计':<10}{metrics['n_total']:>4}{metrics['hit@1']:>8.3f}"
          f"{metrics['hit@3']:>8.3f}{metrics['false_reject_rate']:>8.3f}"
          f"{metrics['false_accept_rate']:>8.3f}{metrics['silent_error']:>6}"
          f"{metrics['gate_hit']:>8.3f}")


async def main(args: argparse.Namespace) -> None:
    if args.cases:
        cases = load_cases(args.cases)
        source = f"{args.cases}（{len(cases)} 条）"
    else:
        cases = DEFAULT_CASES
        source = f"内置用例（{len(cases)} 条）"

    embedder = get_embedder()
    async with AsyncSessionLocal() as session:
        rows, metrics = await run(
            session, args.course_id, cases, args.rerank, args.rewrite
        )

    metrics.update(
        {
            "embedder": type(embedder).__name__,
            "dim": embedder.dim,
            "course_id": args.course_id,
            "cases_source": source,
            "rerank": bool(args.rerank),
            # 实际生效的后端（未传 --rerank 时记 off，避免汇总表误标）
            "rerank_backend": settings.RERANK_BACKEND if args.rerank else "off",
            "rerank_config": settings.RERANK_BACKEND,
            "rewrite": bool(args.rewrite),
            "rewrite_enabled": settings.QUERY_REWRITE_ENABLED,
        }
    )
    Path(args.out).write_text(
        json.dumps({"metrics": metrics, "rows": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"课程 {args.course_id} | {source} | embedder={type(embedder).__name__}"
          f" | rerank={settings.RERANK_BACKEND if args.rerank else 'off'}"
          f" | rewrite={'on' if args.rewrite and settings.QUERY_REWRITE_ENABLED else 'off'}")
    print_table(metrics)
    print(f"\n平均单条耗时 {metrics['avg_latency_ms']} ms"
          f" | relevance 中位数 {metrics['relevance_median']}")
    print(f"结果已写入 {args.out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="检索能力基准测试")
    parser.add_argument("--cases", help="CSV 用例文件（category,query,gold）")
    parser.add_argument("--course-id", type=int, default=DEFAULT_COURSE_ID, help="课程 id")
    parser.add_argument("--out", default="/tmp/bench.json", help="结果 JSON 路径")
    parser.add_argument("--rerank", action="store_true", help="启用重排（需 RERANK_BACKEND 非 off）")
    parser.add_argument("--rewrite", action="store_true", help="启用查询改写（需 QUERY_REWRITE_ENABLED）")
    # 兼容旧用法：第一个位置参数视为输出路径
    parser.add_argument("legacy_out", nargs="?", help=argparse.SUPPRESS)
    parsed = parser.parse_args()
    if parsed.legacy_out and parsed.out == "/tmp/bench.json":
        parsed.out = parsed.legacy_out
    asyncio.run(main(parsed))
