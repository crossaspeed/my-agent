"""PDF 解析器（PyMuPDF）。

要点：block/line/span 层级取字号与粗体判定标题；同坐标重复文本识别页眉页脚；
find_tables 抽取表格转 markdown；扫描页标记 needs_ocr 由上层决定是否 OCR。
"""

from __future__ import annotations

import statistics
from collections import Counter
from pathlib import Path
from typing import Any

import pymupdf as fitz  # PyMuPDF

from app.core.exceptions import ParseFailed
from app.core.logging import get_logger
from app.rag.parsers.base import BaseParser, ParseResult, Segment, detect_heading_level, join_lines

logger = get_logger(__name__)


class PDFParser(BaseParser):
    file_type = "pdf"

    def parse(self, path: Path) -> ParseResult:
        try:
            doc = fitz.open(path)
        except Exception as exc:
            raise ParseFailed(f"PDF 打开失败：{exc}") from exc
        if doc.needs_pass:
            raise ParseFailed("PDF 已加密，请先解密后再上传")

        pages_raw: list[dict[str, Any]] = []
        sizes_all: list[float] = []
        needs_ocr_pages: list[int] = []

        for pno in range(doc.page_count):
            page = doc[pno]
            height = page.rect.height or 1
            blocks: list[dict[str, Any]] = []
            data = page.get_text("dict")
            for block in data.get("blocks", []):
                if block.get("type") != 0:
                    continue
                lines = block.get("lines", [])
                texts: list[str] = []
                max_size = 0.0
                bold = False
                bbox = block.get("bbox", (0, 0, 0, 0))
                for line in lines:
                    spans = line.get("spans", [])
                    line_text = "".join(s.get("text", "") for s in spans).strip()
                    if not line_text:
                        continue
                    texts.append(line_text)
                    for span in spans:
                        size = float(span.get("size", 0) or 0)
                        max_size = max(max_size, size)
                        if span.get("flags", 0) & 16:
                            bold = True
                        sizes_all.append(size)
                text = join_lines(texts)
                if not text:
                    continue
                blocks.append(
                    {
                        "text": text,
                        "size": max_size,
                        "bold": bold,
                        "bbox": bbox,
                        "y0": bbox[1] / height,
                        "y1": bbox[3] / height,
                    }
                )

            # 扫描页兜底标记
            stripped = page.get_text().strip()
            if len(stripped) < 20 and page.get_images():
                needs_ocr_pages.append(pno + 1)

            pages_raw.append({"page_no": pno + 1, "blocks": blocks})

        body_size = statistics.median(sizes_all) if sizes_all else 10.0
        repeated = self._detect_repeated(pages_raw)

        segments: list[Segment] = []
        for page in pages_raw:
            tables = self._extract_tables(doc[page["page_no"] - 1])
            for md in tables:
                segments.append(
                    Segment(text=md, page_no=page["page_no"], style={"is_table": True}, kind="table")
                )
            for block in page["blocks"]:
                text = block["text"].strip()
                if not text or text in repeated:
                    continue
                level = detect_heading_level(block["size"], body_size, block["bold"], text)
                segments.append(
                    Segment(
                        text=text,
                        page_no=page["page_no"],
                        style={
                            "font_size": round(block["size"], 1),
                            "bold": block["bold"],
                            "level": level,
                            "is_title": level > 0,
                        },
                        kind="title" if level > 0 else "paragraph",
                    )
                )

        meta: dict[str, Any] = {
            "title": (doc.metadata or {}).get("title") or "",
            "author": (doc.metadata or {}).get("author") or "",
            "repeated_lines": sorted(repeated)[:20],
            "ocr_pages": needs_ocr_pages,
            "parser": "pymupdf",
        }
        result = ParseResult(segments=segments, page_count=doc.page_count, meta=meta)
        doc.close()
        if not segments:
            raise ParseFailed("未提取到有效文本（可能是纯图片扫描件）")
        return result

    # ---------------- 内部工具 ----------------

    @staticmethod
    def _detect_repeated(pages_raw: list[dict[str, Any]]) -> set[str]:
        """同一文本在 ≥60% 页面出现且位于页首/页尾 → 判为页眉页脚。"""
        if len(pages_raw) < 3:
            return set()
        counter: Counter[str] = Counter()
        for page in pages_raw:
            seen: set[str] = set()
            for block in page["blocks"]:
                if len(block["text"]) > 60:
                    continue
                if block["y0"] < 0.12 or block["y1"] > 0.9:
                    norm = block["text"].strip()
                    if norm and norm not in seen:
                        seen.add(norm)
                        counter[norm] += 1
        threshold = max(2, int(len(pages_raw) * 0.6))
        return {text for text, count in counter.items() if count >= threshold}

    @staticmethod
    def _extract_tables(page: fitz.Page) -> list[str]:
        try:
            found = page.find_tables()
        except Exception:  # 旧版 PyMuPDF 或复杂版面
            return []
        out: list[str] = []
        for table in getattr(found, "tables", []):
            try:
                rows = table.extract()
            except Exception:
                continue
            rows = [[(cell or "").replace("\n", " ").strip() for cell in row] for row in rows]
            rows = [row for row in rows if any(row)]
            if len(rows) < 2:
                continue
            header, body = rows[0], rows[1:]
            width = max(len(header), max((len(r) for r in body), default=0))
            header = header + [""] * (width - len(header))
            lines = [
                "| " + " | ".join(header) + " |",
                "| " + " | ".join(["---"] * width) + " |",
            ]
            for row in body:
                row = row + [""] * (width - len(row))
                lines.append("| " + " | ".join(row) + " |")
            out.append("\n".join(lines))
        return out
