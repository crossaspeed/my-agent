"""结构感知分块（计划书 8.4）。

策略：按标题层级分组 → 组内按段落累积到 target_chars → 超长按句切 → 句子级重叠 →
表格/代码块整体保护，不切碎（表头单独成块会严重损害检索）。
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from typing import Any

from app.core.config import settings
from app.rag.parsers.base import Segment

SENTENCE_SPLIT = re.compile(r"(?<=[。！？；!?;\n])")
CJK = re.compile(r"[\u4e00-\u9fff]")


@dataclass
class Chunk:
    content: str
    page_no: int | None = None
    slide_no: int | None = None
    heading_path: str | None = None
    char_start: int = 0
    char_end: int = 0
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def token_count(self) -> int:
        """中文近似 token 数（论文中说明：字符数 × 0.75 作为上界估计）。"""
        return max(1, int(len(self.content) * 0.75))


@dataclass
class ChunkConfig:
    target_chars: int = settings.CHUNK_TARGET_CHARS
    max_chars: int = settings.CHUNK_MAX_CHARS
    min_chars: int = settings.CHUNK_MIN_CHARS
    overlap_chars: int = settings.CHUNK_OVERLAP_CHARS
    keep_tables_whole: bool = True
    # size：只按字数（默认，跨页合并）/ heading：标题变更断开 / slide：换页断开
    boundary: str = settings.CHUNK_BOUNDARY


def _split_sentences(text: str, limit: int) -> list[str]:
    parts = [p for p in SENTENCE_SPLIT.split(text) if p and p.strip()]
    out: list[str] = []
    buf = ""
    for part in parts:
        if len(part) > limit:
            if buf:
                out.append(buf)
                buf = ""
            # 在逗号处找最近切点
            while len(part) > limit:
                cut = max(part.rfind("，", 0, limit), part.rfind("、", 0, limit),
                          part.rfind(",", 0, limit))
                if cut < limit * 0.5:
                    cut = limit
                out.append(part[:cut])
                part = part[cut:]
            if part:
                buf = part
            continue
        if len(buf) + len(part) > limit and buf:
            out.append(buf)
            buf = part
        else:
            buf += part
    if buf:
        out.append(buf)
    return [o for o in out if o.strip()]


def _tail_overlap(text: str, overlap: int) -> str:
    if overlap <= 0 or len(text) <= overlap:
        return ""
    tail = text[-overlap:]
    # 尽量从句号后开始
    for sep in ("。", "；", "！", "？", "\n"):
        idx = tail.find(sep)
        if 0 <= idx < overlap * 0.6:
            return tail[idx + 1 :].strip()
    return tail.strip()


def _table_rows(md: str) -> tuple[list[str], list[str]]:
    lines = [line for line in md.splitlines() if line.strip()]
    if len(lines) < 3:
        return [], lines
    return [lines[0], lines[1]], lines[2:]


def _chunk_table(md: str, cfg: ChunkConfig) -> list[str]:
    if len(md) <= cfg.max_chars:
        return [md]
    header, rows = _table_rows(md)
    if not rows:
        return _split_sentences(md, cfg.max_chars)
    out: list[str] = []
    buf = "\n".join(header)
    for row in rows:
        if len(buf) + len(row) + 1 > cfg.max_chars and buf:
            out.append(buf)
            buf = "\n".join(header) + "\n" + row  # 重复表头
        else:
            buf += "\n" + row
    if buf:
        out.append(buf)
    return out


def chunk_segments(segments: list[Segment], cfg: ChunkConfig | None = None) -> list[Chunk]:
    cfg = cfg or ChunkConfig()
    # 1) 标题栈 → heading_path
    units: list[dict[str, Any]] = []
    stack: list[tuple[int, str]] = []
    offset = 0
    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue
        level = int(seg.style.get("level") or 0) if seg.style else 0
        if seg.kind == "title":
            while stack and stack[-1][0] >= max(level, 1):
                stack.pop()
            stack.append((max(level, 1), text))
            path = " > ".join(name for _, name in stack)
            if len(path) > 500:
                path = path[-500:]
            units.append(
                {
                    "text": text,
                    "kind": "title",
                    "page_no": seg.page_no,
                    "slide_no": seg.slide_no,
                    "heading_path": path,
                    "start": offset,
                }
            )
            offset += len(text) + 1
            continue
        path = " > ".join(name for _, name in stack) or None
        units.append(
            {
                "text": text,
                "kind": seg.kind,
                "page_no": seg.page_no,
                "slide_no": seg.slide_no,
                "heading_path": path,
                "start": offset,
            }
        )
        offset += len(text) + 1

    # 2) 打包
    chunks: list[Chunk] = []
    buf: list[str] = []
    buf_len = 0
    start_page: int | None = None
    start_slide: int | None = None
    start_heading: str | None = None
    start_offset = 0
    # 块内是否已装入正文（同一个块可能先装标题再装正文，块的章节归属应以正文为准）
    has_body = False
    overlap_prefix = ""
    # 当前块所属的结构范围（heading/slide 模式下用于判断是否越界）
    buf_key: Any = None

    def scope_key(unit: dict[str, Any]) -> Any:
        """结构边界的判定键；size 模式返回 None（即不做结构判断）。"""
        if cfg.boundary == "slide":
            slide = unit["slide_no"]
            return ("slide", slide) if slide is not None else ("page", unit["page_no"])
        if cfg.boundary == "heading":
            return ("heading", unit["heading_path"])
        return None

    def flush(use_overlap: bool = True) -> None:
        nonlocal buf, buf_len, start_page, start_slide, start_heading, start_offset, has_body
        nonlocal overlap_prefix, buf_key
        content = "\n".join(buf).strip()
        if not content:
            buf, buf_len = [], 0
            buf_key = None
            return
        chunks.append(
            Chunk(
                content=content,
                page_no=start_page,
                slide_no=start_slide,
                heading_path=start_heading,
                char_start=start_offset,
                char_end=start_offset + len(content),
                meta={"overlap_prefix": bool(overlap_prefix) if use_overlap else False},
            )
        )
        buf, buf_len = [], 0
        start_page = start_slide = start_heading = None
        has_body = False
        buf_key = None
        if not use_overlap:
            overlap_prefix = ""

    for unit in units:
        text = unit["text"]
        kind = unit["kind"]

        if kind == "table" and cfg.keep_tables_whole:
            flush(use_overlap=False)
            for piece in _chunk_table(text, cfg):
                chunks.append(
                    Chunk(
                        content=piece,
                        page_no=unit["page_no"],
                        slide_no=unit["slide_no"],
                        heading_path=unit["heading_path"],
                        char_start=unit["start"],
                        char_end=unit["start"] + len(piece),
                        meta={"is_table": True},
                    )
                )
            continue

        # 结构边界：跨标题 / 跨页时强制断开，且不把上一块尾部带进新块。
        # 否则相邻块共享 100 字重叠，检索与重排都难以区分“上一块 / 这一块”。
        key = scope_key(unit)
        if cfg.boundary != "size" and buf and key != buf_key:
            flush(use_overlap=False)

        pieces = _split_sentences(text, cfg.max_chars) if len(text) > cfg.max_chars else [text]
        for piece in pieces:
            piece = piece.strip()
            if not piece:
                continue
            if buf_len + len(piece) > cfg.target_chars and buf_len >= cfg.min_chars:
                flush(use_overlap=True)
                overlap_prefix = (
                    _tail_overlap(chunks[-1].content, cfg.overlap_chars) if chunks else ""
                )
                if overlap_prefix:
                    buf = [overlap_prefix]
                    buf_len = len(overlap_prefix)
                start_page = unit["page_no"]
                start_slide = unit["slide_no"]
                start_heading = unit["heading_path"]
                start_offset = max(0, unit["start"] - len(overlap_prefix))
            if not buf:
                start_page = unit["page_no"]
                start_slide = unit["slide_no"]
                start_heading = unit["heading_path"]
                start_offset = unit["start"]
                has_body = False
                buf_key = key
            elif not has_body and kind != "title":
                # 块首是标题、随后装入正文：把块归属升级为正文所属章节，元数据更精确
                start_heading = unit["heading_path"]
            buf.append(piece)
            buf_len += len(piece) + 1
            if kind != "title":
                has_body = True
    flush()

    # 3) 过短块向后合并（只在同一结构范围内合并，跨页/跨节一律不并）
    merged: list[Chunk] = []
    for chunk in chunks:
        same_scope = bool(merged) and chunk.heading_path == merged[-1].heading_path
        if cfg.boundary == "slide":
            same_scope = (
                bool(merged)
                and chunk.slide_no == merged[-1].slide_no
                and chunk.page_no == merged[-1].page_no
            )
        if (
            merged
            and len(chunk.content) < cfg.min_chars
            and same_scope
            and len(merged[-1].content) + len(chunk.content) <= cfg.max_chars
        ):
            merged[-1].content = merged[-1].content + "\n" + chunk.content
            merged[-1].char_end = chunk.char_end
            continue
        merged.append(chunk)
    return merged


def chunk_stats(chunks: list[Chunk]) -> dict[str, Any]:
    if not chunks:
        return {"count": 0}
    lengths = [len(c.content) for c in chunks]
    mean = statistics.fmean(lengths)
    std = statistics.pstdev(lengths) if len(lengths) > 1 else 0.0
    stats = {
        "count": len(chunks),
        "mean_len": round(mean, 1),
        "std_len": round(std, 1),
        "max_len": max(lengths),
        "min_len": min(lengths),
        "over_max": sum(1 for n in lengths if n > settings.CHUNK_MAX_CHARS * 1.2),
        "under_min": sum(1 for n in lengths if n < settings.CHUNK_MIN_CHARS),
        "heading_ratio": round(sum(1 for c in chunks if c.heading_path) / len(chunks), 3),
    }
    if mean and std / mean > 0.8:
        stats["warning"] = "分块长度离散度偏高（std/mean > 0.8），该文档的版面结构可能不规则"
    return stats
