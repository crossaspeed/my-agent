"""PPTX 解析器（python-pptx）：标题占位符、表格、备注。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pptx import Presentation
from pptx.enum.shapes import PP_PLACEHOLDER

from app.core.exceptions import ParseFailed
from app.rag.parsers.base import BaseParser, ParseResult, Segment

TITLE_TYPES = {
    PP_PLACEHOLDER.TITLE,
    PP_PLACEHOLDER.CENTER_TITLE,
    PP_PLACEHOLDER.VERTICAL_TITLE,
}


class PPTXParser(BaseParser):
    file_type = "pptx|ppt"

    def parse(self, path: Path) -> ParseResult:
        try:
            prs = Presentation(str(path))
        except Exception as exc:
            raise ParseFailed(f"PPTX 打开失败：{exc}") from exc

        segments: list[Segment] = []
        for idx, slide in enumerate(prs.slides, start=1):
            for shape in slide.shapes:
                if getattr(shape, "has_table", False) and shape.has_table:
                    md = self._table_to_markdown(shape.table)
                    if md:
                        segments.append(
                            Segment(text=md, slide_no=idx, kind="table", style={"is_table": True})
                        )
                    continue
                if not getattr(shape, "has_text_frame", False) or not shape.has_text_frame:
                    continue
                is_title = False
                try:
                    if shape.is_placeholder:
                        is_title = shape.placeholder_format.type in TITLE_TYPES
                except (ValueError, AttributeError):
                    is_title = False
                paragraphs = [
                    p.text.strip() for p in shape.text_frame.paragraphs if p.text.strip()
                ]
                if not paragraphs:
                    continue
                for i, text in enumerate(paragraphs):
                    kind = "title" if is_title and i == 0 else "paragraph"
                    level = 1 if kind == "title" else 0
                    segments.append(
                        Segment(
                            text=text,
                            slide_no=idx,
                            kind=kind,
                            style={"is_title": kind == "title", "level": level, "shape": shape.shape_type and str(shape.shape_type)},
                        )
                    )
            # 备注单独成段
            if slide.has_notes_slide:
                notes = (slide.notes_slide.notes_text_frame.text or "").strip()
                if notes:
                    segments.append(
                        Segment(text=notes, slide_no=idx, kind="note", style={"is_note": True})
                    )

        if not segments:
            raise ParseFailed("未提取到有效文本（PPT 可能只有图片）")
        meta: dict[str, Any] = {
            "title": (prs.core_properties.title or "") if prs.core_properties else "",
            "author": (prs.core_properties.author or "") if prs.core_properties else "",
            "parser": "python-pptx",
        }
        return ParseResult(segments=segments, page_count=len(prs.slides), meta=meta)

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
