"""把 retrieval_bench.py 的原始结果重新汇总成统一口径的指标表。

用途：不同版本（hash/bge-m3、有无门禁）跑出的 JSON 用同一套定义复算，
避免"改了指标定义导致看起来变好"。

用法：
    python scripts/bench_report.py a.json b.json ...
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def summarize(payload: dict[str, Any]) -> dict[str, Any]:
    rows = payload["rows"]
    in_scope = [r for r in rows if r["gold"]]
    out_scope = [r for r in rows if not r["gold"]]
    n_in, n_out = len(in_scope), len(out_scope)

    def rate(num: int, den: int) -> float:
        return round(num / den, 4) if den else 0.0

    return {
        "embedder": payload["metrics"].get("embedder"),
        "rerank": payload["metrics"].get("rerank_backend", "off"),
        "hit@1": rate(sum(r["hit@1"] for r in in_scope), n_in),
        "hit@3": rate(sum(r["hit@3"] for r in in_scope), n_in),
        "false_reject": rate(sum(1 for r in in_scope if not r["accepted"]), n_in),
        "false_accept": rate(sum(1 for r in out_scope if r["accepted"]), n_out),
        # 门禁放行、但保留的证据里根本没有正确答案 —— 最危险的一类错误
        "silent_error": sum(1 for r in in_scope if r["accepted"] and not r["hit@3"]),
        # 门禁选中的那条证据是否就是答案（衡量门禁本身选得准不准）
        # 早期结果没有记录 gate_chunk，此列按可统计样本计算
        "gate_hit": rate(
            sum(1 for r in in_scope if r.get("gate_chunk") in r["gold"]),
            sum(1 for r in in_scope if r.get("gate_chunk") is not None),
        ),
        "avg_relevance": round(
            sum(r["relevance_top1"] for r in rows) / len(rows), 4
        ),
    }


def main(paths: list[str]) -> None:
    print("| 配置 | embedder | 重排 | Hit@1 | Hit@3 | 误拒率 | 误纳率 | 静默错误 | 门禁命中 | 平均相关度 |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for path in paths:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        m = summarize(payload)
        print(
            f"| {Path(path).stem} | {m['embedder']} | {m['rerank']} | {m['hit@1']:.3f} | {m['hit@3']:.3f} "
            f"| {m['false_reject']:.3f} | {m['false_accept']:.3f} | {m['silent_error']} "
            f"| {m['gate_hit']:.3f} | {m['avg_relevance']:.3f} |"
        )


if __name__ == "__main__":
    main(sys.argv[1:] or ["/tmp/bench.json"])
