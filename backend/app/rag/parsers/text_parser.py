"""MD / TXT 解析器。"""

from __future__ import annotations

import re
from pathlib import Path

from app.core.exceptions import ParseFailed
from app.rag.parsers.base import BaseParser, ParseResult, Segment

_MD_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


class TextParser(BaseParser):
    file_type = "md|markdown|txt"

    def parse(self, path: Path) -> ParseResult:
        raw = ""
        for encoding in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
            try:
                raw = path.read_text(encoding=encoding)
                break
            except UnicodeDecodeError:
                continue
        if not raw.strip():
            raise ParseFailed("未提取到有效文本（文件为空）")

        is_md = path.suffix.lower() in (".md", ".markdown")
        segments: list[Segment] = []
        buffer: list[str] = []

        def flush() -> None:
            if buffer:
                text = "\n".join(buffer).strip()
                if text:
                    segments.append(Segment(text=text, kind="paragraph"))
                buffer.clear()

        for line in raw.splitlines():
            if is_md:
                m = _MD_HEADING.match(line)
                if m:
                    flush()
                    level = len(m.group(1))
                    segments.append(
                        Segment(
                            text=m.group(2).strip(),
                            kind="title",
                            style={"is_title": True, "level": level},
                        )
                    )
                    continue
                if line.strip().startswith("```"):
                    flush()
                    segments.append(Segment(text=line.strip(), kind="code"))
                    continue
            if not line.strip():
                flush()
            else:
                buffer.append(line)
        flush()

        if not segments:
            raise ParseFailed("未提取到有效文本")
        return ParseResult(
            segments=segments, page_count=1, meta={"parser": "text", "format": "md" if is_md else "txt"}
        )
