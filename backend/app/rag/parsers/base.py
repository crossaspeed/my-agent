"""解析器协议与数据结构（类型定义冻结，见计划书 8.2）。"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_CJK = re.compile(r"[\u4e00-\u9fff]")


@dataclass
class Segment:
    text: str
    page_no: int | None = None
    slide_no: int | None = None
    style: dict[str, Any] = field(default_factory=dict)
    kind: str = "paragraph"  # paragraph|title|table|list|code|caption|note


@dataclass
class ParseResult:
    segments: list[Segment]
    page_count: int
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def char_count(self) -> int:
        return sum(len(s.text) for s in self.segments)


class BaseParser(ABC):
    """所有解析器的统一入口。"""

    file_type: str = ""

    def supports(self, file_type: str) -> bool:
        return file_type.lower().lstrip(".") in self.file_type.split("|")

    @abstractmethod
    def parse(self, path: Path) -> ParseResult: ...


def join_lines(lines: list[str]) -> str:
    """中文直接拼接，英文之间补空格；保留原有段落分隔。"""
    out = ""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if not out:
            out = line
            continue
        prev = out[-1]
        nxt = line[0]
        need_space = not (_CJK.match(prev) or _CJK.match(nxt)) and prev not in "-—/"
        out += (" " if need_space else "") + line
    return out


def detect_heading_level(font_size: float, body_size: float, bold: bool, text: str) -> int:
    """返回 0 表示正文，1..4 表示标题层级。"""
    if len(text) > 80:
        return 0
    if body_size <= 0:
        return 0
    ratio = font_size / body_size
    if ratio >= 1.55:
        return 1
    if ratio >= 1.3:
        return 2
    if ratio >= 1.12:
        return 3
    if bold and len(text) <= 40 and not text.endswith(("。", "，", "；")):
        return 4
    return 0
