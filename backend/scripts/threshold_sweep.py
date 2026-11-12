"""门禁阈值扫描：用已保存的评测结果离线复算，不必反复改 .env 重启。

背景：`accepted` 只取决于两条已落盘的信号——
    relevance_top1（候选集最大相关度）与 unknown_ratio（查询词未登录率），
因此任意阈值的误拒/误纳/静默错误都可以从同一份 JSON 直接算出，
避免"改一次配置、跑一遍评测"的来回折腾，也保证口径完全一致。

用法：
    python scripts/threshold_sweep.py eval_out/bench.json
    python scripts/threshold_sweep.py a.json b.json --markdown
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

# 与 app.core.config 保持一致；由 --floor / --unknown 覆盖
DEFAULT_UNKNOWN = 0.5
DEFAULT_FLOOR = 0.5


def accepted(row: dict[str, Any], threshold: float, unknown: float, floor: float) -> bool:
    u = row.get("unknown_ratio")
    off_syllabus = u is not None and u >= unknown and row["relevance_top1"] < floor
    return row["relevance_top1"] >= threshold and not off_syllabus


def sweep(
    rows: list[dict[str, Any]],
    thresholds: list[float],
    unknown: float,
    floor: float,
) -> list[dict[str, Any]]:
    ins = [r for r in rows if r["gold"]]
    outs = [r for r in rows if not r["gold"]]
    out: list[dict[str, Any]] = []
    for t in thresholds:
        fr = sum(1 for r in ins if not accepted(r, t, unknown, floor))
        fa = sum(1 for r in outs if accepted(r, t, unknown, floor))
        silent = sum(
            1 for r in ins if accepted(r, t, unknown, floor) and not r["hit@3"]
        )
        out.append(
            {
                "threshold": t,
                "false_reject": fr / len(ins) if ins else 0.0,
                "false_reject_n": fr,
                "false_accept": fa / len(outs) if outs else 0.0,
                "false_accept_n": fa,
                "silent_error": silent,
                # 等权代价：拒答与误纳都算一次错，便于挑平衡点
                "cost": (fr / len(ins) if ins else 0.0) + (fa / len(outs) if outs else 0.0),
            }
        )
    return out


def print_table(name: str, data: list[dict[str, Any]], markdown: bool) -> None:
    print(f"\n## {name}\n")
    if markdown:
        print("| 阈值 | 误拒率 | 误拒数 | 误纳率 | 误纳数 | 静默错误 | 误拒+误纳 |")
        print("|---|---|---|---|---|---|---|")
    else:
        print(f"{'阈值':>6}{'误拒率':>9}{'误拒数':>7}{'误纳率':>9}{'误纳数':>7}"
              f"{'静默':>6}{'误拒+误纳':>10}")
    best = min(data, key=lambda d: d["cost"])
    for d in data:
        mark = "  ← 最优" if d is best else ""
        if markdown:
            print(f"| {d['threshold']:.2f} | {d['false_reject']:.3f} | {d['false_reject_n']} | "
                  f"{d['false_accept']:.3f} | {d['false_accept_n']} | {d['silent_error']} | "
                  f"{d['cost']:.3f}{mark} |")
        else:
            print(f"{d['threshold']:>6.2f}{d['false_reject']:>9.3f}{d['false_reject_n']:>7}"
                  f"{d['false_accept']:>9.3f}{d['false_accept_n']:>7}"
                  f"{d['silent_error']:>6}{d['cost']:>10.3f}{mark}")
    print(f"\n最优阈值（误拒+误纳最小）：{best['threshold']:.2f}"
          f"（误拒 {best['false_reject']:.3f} / 误纳 {best['false_accept']:.3f}）")


def main(args: argparse.Namespace) -> None:
    thresholds = [round(x / 100, 2) for x in range(
        int(args.start * 100), int(args.end * 100) + 1, int(args.step * 100)
    )]
    for path in args.files:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        m = payload.get("metrics", {})
        tag = (f"{Path(path).stem} | rerank={m.get('rerank_backend', 'off')} "
               f"| Hit@1 {m.get('hit@1', 0):.3f} / Hit@3 {m.get('hit@3', 0):.3f}")
        data = sweep(payload["rows"], thresholds, args.unknown, args.floor)
        print_table(tag, data, args.markdown)
        print("\n注：Hit@1 / Hit@3 只由检索排序决定，不随阈值变化；"
              "阈值只影响“答不答”，不影响“答得对不对”。")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="门禁阈值扫描（离线复算）")
    p.add_argument("files", nargs="+", help="retrieval_bench 产出的结果 JSON")
    p.add_argument("--start", type=float, default=0.30)
    p.add_argument("--end", type=float, default=0.80)
    p.add_argument("--step", type=float, default=0.05)
    p.add_argument("--unknown", type=float, default=DEFAULT_UNKNOWN,
                   help="MAX_UNKNOWN_TERM_RATIO")
    p.add_argument("--floor", type=float, default=DEFAULT_FLOOR,
                   help="OFF_SYLLABUS_RELEVANCE_FLOOR")
    p.add_argument("--markdown", action="store_true")
    main(p.parse_args())
