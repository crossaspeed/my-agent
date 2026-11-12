"""把 cases.csv 的 gold 从旧分块迁移到新分块（按字符区间重叠），并支持先导出快照。

重新分块（改 CHUNK_BOUNDARY / 重新解析）后，chunk id 会全部变化，标注会失效。
chunker 为每块记录了 `char_start/char_end`（在清洗后文本流中的区间），
同一文档重新解析后区间仍然可比，因此可以用“区间重叠”把 gold 自动迁移过去。

用法（容器内）：
    # 1) 改造前先导出快照
    python -m scripts.remap_cases --course-id 8 --dump-out /tmp/ranges-old.json

    # 2) 重新解析后，用快照把用例迁移到新 id
    python -m scripts.remap_cases --course-id 8 --old /tmp/ranges-old.json \
        --cases /tmp/cases.csv --out /tmp/cases-new.csv

    # 3) 只想看看当前分块规模
    python -m scripts.remap_cases --course-id 8 --stats
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.db.base import AsyncSessionLocal
from app.db.models import Document, DocumentChunk


async def fetch_chunks(course_id: int) -> list[dict[str, Any]]:
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(
                    DocumentChunk.id,
                    DocumentChunk.document_id,
                    DocumentChunk.chunk_index,
                    DocumentChunk.char_start,
                    DocumentChunk.char_end,
                    DocumentChunk.slide_no,
                    DocumentChunk.heading_path,
                    Document.filename,
                )
                .join(Document, Document.id == DocumentChunk.document_id)
                .where(DocumentChunk.course_id == course_id, Document.status == "ready")
                .order_by(DocumentChunk.document_id, DocumentChunk.chunk_index)
            )
        ).all()
    return [
        {
            "id": int(r[0]),
            "document_id": int(r[1]),
            "chunk_index": int(r[2]),
            "char_start": r[3],
            "char_end": r[4],
            "slide_no": r[5],
            "heading": r[6],
            "filename": r[7],
        }
        for r in rows
    ]


def load_cases(path: str) -> tuple[list[str], list[dict[str, str]]]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames or [])
        rows = [{k: (v or "") for k, v in r.items()} for r in reader]
    return fields, rows


def parse_gold(raw: str) -> list[int]:
    return [int(x) for x in raw.replace(" ", "").split(",") if x]


def remap_gold(
    gold: list[int],
    old_by_id: dict[int, dict[str, Any]],
    new_by_doc: dict[int, list[dict[str, Any]]],
    min_cover: float = 0.3,
) -> tuple[list[int], list[str]]:
    """把一批旧 gold id 映射成新 id：取与旧区间重叠的新块（覆盖率≥min_cover）。"""
    mapped: list[int] = []
    notes: list[str] = []
    for gid in gold:
        old = old_by_id.get(gid)
        if not old:
            notes.append(f"旧 id {gid} 不在快照里")
            continue
        s, e = old.get("char_start"), old.get("char_end")
        if s is None or e is None or e <= s:
            notes.append(f"旧 id {gid} 缺字符区间，无法映射")
            continue
        length = e - s
        cands = []
        for new in new_by_doc.get(old["document_id"], []):
            ns, ne = new.get("char_start"), new.get("char_end")
            if ns is None or ne is None:
                continue
            overlap = min(e, ne) - max(s, ns)
            if overlap > 0:
                cands.append((overlap / length, new["id"]))
        if not cands:
            notes.append(f"旧 id {gid} 在新分块里找不到重叠块")
            continue
        cands.sort(reverse=True)
        kept = [cid for cover, cid in cands if cover >= min_cover] or [cands[0][1]]
        mapped.extend(kept)
    # 去重保序
    seen: set[int] = set()
    out = [x for x in mapped if not (x in seen or seen.add(x))]
    return out, notes


async def run(args: argparse.Namespace) -> None:
    chunks = await fetch_chunks(args.course_id)
    if args.stats:
        docs = {c["document_id"] for c in chunks}
        heads = {c["heading"] for c in chunks}
        lens = [c["char_end"] - c["char_start"] for c in chunks if c["char_start"] is not None]
        print(
            f"课程 {args.course_id}: 分块 {len(chunks)} | 文档 {len(docs)} | 标题 {len(heads)}"
            + (f" | 平均长度 {sum(lens) / len(lens):.0f}" if lens else "")
        )
        return

    if args.dump_out:
        Path(args.dump_out).write_text(
            json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"已导出 {len(chunks)} 个分块的区间快照 → {args.dump_out}")
        return

    if not (args.old and args.cases and args.out):
        raise SystemExit("需要 --old / --cases / --out（或使用 --dump-out / --stats）")

    old = json.loads(Path(args.old).read_text(encoding="utf-8"))
    old_by_id = {int(c["id"]): c for c in old}
    new_by_doc: dict[int, list[dict[str, Any]]] = {}
    for c in chunks:
        new_by_doc.setdefault(c["document_id"], []).append(c)

    fields, rows = load_cases(args.cases)
    changed = failed = 0
    for row in rows:
        raw = row.get("gold", "")
        if not raw.strip():
            continue
        gold = parse_gold(raw)
        new_gold, notes = remap_gold(gold, old_by_id, new_by_doc, args.min_cover)
        if not new_gold:
            failed += 1
            row["note"] = (row.get("note", "") + "；remap 失败").strip("；")
            continue
        if set(new_gold) != set(gold):
            changed += 1
        row["gold"] = ",".join(str(x) for x in new_gold)
        if notes:
            row["note"] = (row.get("note", "") + "；" + "；".join(notes)).strip("；")

    with open(args.out, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        writer.writerows(rows)
    print(f"已写出 {args.out}：{len(rows)} 条，gold 变化 {changed} 条，映射失败 {failed} 条")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="cases.csv 的 gold 跨分块迁移")
    p.add_argument("--course-id", type=int, required=True)
    p.add_argument("--dump-out", help="导出当前分块的字符区间快照")
    p.add_argument("--old", help="改造前的快照 JSON")
    p.add_argument("--cases", help="待迁移的用例 CSV")
    p.add_argument("--out", help="迁移后的用例 CSV")
    p.add_argument("--min-cover", type=float, default=0.3, help="新块覆盖旧块的最低比例")
    p.add_argument("--stats", action="store_true", help="只打印当前分块规模")
    asyncio.run(run(p.parse_args()))
