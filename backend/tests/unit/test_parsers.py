"""解析器单元测试（无需真实 PDF，覆盖文本/Markdown 与类型分发）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.exceptions import ParseFailed
from app.rag.parsers import get_parser, parse_file
from app.rag.parsers.base import detect_heading_level, join_lines


def test_markdown_heading_and_paragraph(tmp_path: Path):
    path = tmp_path / "demo.md"
    path.write_text("# 第一章\n\n正文第一段内容。\n\n## 1.1 小节\n\n小节正文。", encoding="utf-8")
    result = parse_file(path, "md")
    kinds = [s.kind for s in result.segments]
    assert kinds.count("title") == 2
    titles = [s.text for s in result.segments if s.kind == "title"]
    assert titles == ["第一章", "1.1 小节"]
    assert result.segments[0].style["level"] == 1
    assert result.segments[2].style["level"] == 2


def test_txt_parsing(tmp_path: Path):
    path = tmp_path / "demo.txt"
    path.write_text("第一段内容。\n\n第二段内容。", encoding="utf-8")
    result = parse_file(path, "txt")
    assert len(result.segments) == 2


def test_empty_file_raises(tmp_path: Path):
    path = tmp_path / "empty.txt"
    path.write_text("   \n", encoding="utf-8")
    with pytest.raises(ParseFailed):
        parse_file(path, "txt")


def test_unsupported_type_raises():
    with pytest.raises(ParseFailed):
        get_parser("exe")


def test_parser_dispatch():
    assert get_parser("pdf").file_type == "pdf"
    assert get_parser("ppt").file_type.startswith("pptx")
    assert get_parser("markdown").file_type.startswith("md")


def test_join_lines_cjk_no_space():
    assert join_lines(["三次握手过程", "客户端发送 SYN"]) == "三次握手过程客户端发送 SYN"
    assert join_lines(["hello", "world"]) == "hello world"


def test_detect_heading_level():
    assert detect_heading_level(24, 12, False, "第3章 传输层") == 1
    assert detect_heading_level(16, 12, False, "3.2 TCP") == 2
    assert detect_heading_level(12, 12, False, "这是正文内容，不应被判为标题") == 0
    assert detect_heading_level(12, 12, True, "注意事项") == 4
