"""DOCX 解析器（python-docx）：标题样式、表格、列表、核心属性。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from docx import Document as DocxDocument
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.core.exceptions import ParseFailed
from app.rag.parsers.base import BaseParser, ParseResult, Segment

_HEADING = re.compile(r"heading\s*(\d)|标题\s*(\d)", re.IGNORECASE)


def _style_level(style_name: str) -> int:
    m = _HEADING.search(style_name or "")
    if not m:
        return 0
    return int(m.group(1) or m.group(2) or 1)


class DOCXParser(BaseParser):
    file_type = "docx|doc"

    def parse(self, path: Path) -> ParseResult:
        try:
            doc = DocxDocument(str(path))
        except Exception as exc:
            raise ParseFailed(f"DOCX 打开失败：{exc}") from exc

        segments: list[Segment] = []
        for item in self._iter_blocks(doc):
            if isinstance(item, Table):
                md = self._table_to_markdown(item)
                if md:
                    segments.append(Segment(text=md, kind="table", style={"is_table": True}))
                continue
            text = (item.text or "").strip()
            if not text:
                continue
            style_name = getattr(item.style, "name", "") or ""
            level = _style_level(style_name)
            if level:
                segments.append(
                    Segment(
                        text=text,
                        kind="title",
                        style={"is_title": True, "level": level, "style": style_name},
                    )
                )
            elif style_name.lower().startswith("list"):
                segments.append(Segment(text=f"- {text.lstrip('·•- ')}", kind="list"))
            else:
                segments.append(Segment(text=text, kind="paragraph", style={"style": style_name}))

        if not segments:
            raise ParseFailed("未提取到有效文本")
        props = doc.core_properties
        meta: dict[str, Any] = {
            "title": props.title or "",
            "author": props.author or "",
            "parser": "python-docx",
        }
        return ParseResult(segments=segments, page_count=1, meta=meta)

    @staticmethod
    def _iter_blocks(doc: Any):
        body = doc.element.body
        for child in body.iterchildren():
            tag = child.tag.split("}")[-1]
            if tag == "p":
                yield Paragraph(child, doc)
            elif tag == "tbl":
                yield Table(child, doc)

    @staticmethod
    def _table_to_markdown(table: Any) -> str:
        rows: list[list[str]] = []
        for row in table.rows:
            rows.append([(cell.text or "").replace("\n", " ").strip() for cell in row.cells])
        rows = [r for r in rows if any(r)]
        if len(rows) < 2:
            return ""
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        lines = ["| " + " | ".join(rows[0]) + " |", "| " + " | ".join(["---"] * width) + " |"]
        lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
        return "\n".join(lines)
