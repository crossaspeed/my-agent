"""清洗规则链（计划书 8.3，9 条规则逐条独立可测）。

每条规则都是纯函数：接收 Segment 列表，返回处理后的列表（或统计信息）。
`clean_segments` 按顺序编排并产出 clean_ratio 等论文可用指标。
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from app.rag.parsers.base import Segment

CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
PAGE_NUMBER = re.compile(r"^\s*(第?\s*\d+\s*页(\s*/\s*共?\s*\d+\s*页)?|page\s*\d+(\s*of\s*\d+)?|- ?\d+ ?-|\d+\s*/\s*\d+)\s*$",
                         re.IGNORECASE)
TOC_LINE = re.compile(r"^.{2,60}?[\.\u2026·]{3,}\s*\d{1,3}\s*$")
BULLET_START = re.compile(r"^\s*([•·▪◦‣\-*]|\(?\d+[\.)、]|[（(][一二三四五六七八九十]+[）)]|[一二三四五六七八九十]+、)")
SENTENCE_END = "。！？；：）」』】.!?;:"
CJK_ANY = re.compile(r"[\u4e00-\u9fff]")


@dataclass
class CleanStats:
    raw_chars: int = 0
    clean_chars: int = 0
    dropped_segments: int = 0
    merged_lines: int = 0
    removed_page_numbers: int = 0
    removed_watermarks: int = 0
    removed_toc_pages: int = 0
    removed_duplicates: int = 0

    @property
    def clean_ratio(self) -> float:
        return round(self.clean_chars / self.raw_chars, 4) if self.raw_chars else 1.0

    def to_dict(self) -> dict[str, Any]:
        data = self.__dict__.copy()
        data["clean_ratio"] = self.clean_ratio
        return data


def strip_control_chars(segments: list[Segment]) -> list[Segment]:
    for seg in segments:
        seg.text = CONTROL_CHARS.sub("", seg.text)
    return segments


def remove_page_numbers(segments: list[Segment], stats: CleanStats | None = None) -> list[Segment]:
    out: list[Segment] = []
    for seg in segments:
        if seg.kind != "title" and PAGE_NUMBER.match(seg.text):
            if stats:
                stats.removed_page_numbers += 1
            continue
        out.append(seg)
    return out


def detect_repeated_texts(segments: list[Segment], ratio: float = 0.8,
                          max_len: int = 30) -> set[str]:
    """同一短句在 ≥80% 页面出现 → 水印/页眉页脚。"""
    pages: dict[int, set[str]] = {}
    for seg in segments:
        key = seg.page_no or seg.slide_no or 0
        pages.setdefault(key, set())
        text = seg.text.strip()
        if 2 <= len(text) <= max_len:
            pages[key].add(text)
    if len(pages) < 3:
        return set()
    counter: Counter[str] = Counter()
    for texts in pages.values():
        for text in texts:
            counter[text] += 1
    threshold = max(2, int(len(pages) * ratio))
    return {text for text, n in counter.items() if n >= threshold}


def remove_repeated_texts(segments: list[Segment], repeated: set[str],
                          stats: CleanStats | None = None) -> list[Segment]:
    out = []
    for seg in segments:
        if seg.kind != "title" and seg.text.strip() in repeated:
            if stats:
                stats.removed_watermarks += 1
            continue
        out.append(seg)
    return out


def merge_broken_lines(segments: list[Segment], stats: CleanStats | None = None) -> list[Segment]:
    """PDF 排版硬换行修复：行尾无标点且下一行非列表/标题 → 拼接。"""
    if not segments:
        return segments
    avg_len = sum(len(s.text) for s in segments) / max(len(segments), 1)
    out: list[Segment] = []
    for seg in segments:
        if (
            out
            and seg.kind == "paragraph"
            and out[-1].kind == "paragraph"
            and out[-1].page_no == seg.page_no
            and out[-1].slide_no == seg.slide_no
            and out[-1].text
            and out[-1].text[-1] not in SENTENCE_END
            and not BULLET_START.match(seg.text)
            and len(out[-1].text) > 0.6 * avg_len
        ):
            prev = out[-1]
            joiner = "" if CJK_ANY.search(prev.text[-1]) or CJK_ANY.search(seg.text[0]) else " "
            out[-1] = Segment(
                text=prev.text + joiner + seg.text.strip(),
                page_no=prev.page_no,
                slide_no=prev.slide_no,
                style=prev.style,
                kind=prev.kind,
            )
            if stats:
                stats.merged_lines += 1
            continue
        out.append(seg)
    return out


def normalize_whitespace(segments: list[Segment]) -> list[Segment]:
    for seg in segments:
        text = seg.text.replace("\u3000", " ").replace("\xa0", " ")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        # 表格与代码块保留原始换行结构
        if seg.kind not in ("table", "code"):
            text = text.strip()
        seg.text = text
    return segments


def dedupe_identical(segments: list[Segment], stats: CleanStats | None = None) -> list[Segment]:
    """页内去重（PPT 动画副本 / 重复渲染）。"""
    seen: dict[tuple[int, str], int] = {}
    out: list[Segment] = []
    for seg in segments:
        page = seg.page_no or seg.slide_no or 0
        key = (page, seg.text.strip())
        if len(seg.text) > 12 and key in seen:
            if stats:
                stats.removed_duplicates += 1
            continue
        seen[key] = 1
        out.append(seg)
    return out


def drop_noise(segments: list[Segment], stats: CleanStats | None = None,
               min_len: int = 15) -> list[Segment]:
    out = []
    for seg in segments:
        if seg.kind in ("table", "code"):
            out.append(seg)
            continue
        if seg.kind != "title" and len(seg.text.strip()) < min_len:
            if stats:
                stats.dropped_segments += 1
            continue
        out.append(seg)
    return out


def drop_toc(segments: list[Segment], stats: CleanStats | None = None) -> list[Segment]:
    """连续 ≥5 行「标题……页码」判为目录页，整段丢弃。"""
    out: list[Segment] = []
    run: list[Segment] = []
    for seg in segments:
        if TOC_LINE.match(seg.text.strip()):
            run.append(seg)
            continue
        if len(run) >= 5:
            if stats:
                stats.removed_toc_pages += len(run)
        else:
            out.extend(run)
        run = []
        out.append(seg)
    if len(run) >= 5:
        if stats:
            stats.removed_toc_pages += len(run)
    else:
        out.extend(run)
    return out


def clean_segments(segments: list[Segment]) -> tuple[list[Segment], CleanStats]:
    stats = CleanStats(raw_chars=sum(len(s.text) for s in segments))
    work = [Segment(**vars(s)) for s in segments]  # 不改原对象

    work = strip_control_chars(work)
    work = remove_page_numbers(work, stats)
    repeated = detect_repeated_texts(work)
    work = remove_repeated_texts(work, repeated, stats)
    work = merge_broken_lines(work, stats)
    work = normalize_whitespace(work)
    work = dedupe_identical(work, stats)
    work = drop_noise(work, stats)
    work = drop_toc(work, stats)
    work = [s for s in work if s.text.strip()]

    stats.clean_chars = sum(len(s.text) for s in work)
    return work, stats
