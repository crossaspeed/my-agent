"""解析器注册与分发。"""

from __future__ import annotations

from pathlib import Path

from app.core.exceptions import ParseFailed
from app.rag.parsers.base import BaseParser, ParseResult
from app.rag.parsers.docx_parser import DOCXParser
from app.rag.parsers.pdf_parser import PDFParser
from app.rag.parsers.pptx_parser import PPTXParser
from app.rag.parsers.text_parser import TextParser

SUPPORTED_TYPES = {"pdf", "pptx", "ppt", "docx", "doc", "md", "markdown", "txt"}

_PARSERS: list[BaseParser] = [PDFParser(), PPTXParser(), DOCXParser(), TextParser()]


def get_parser(file_type: str) -> BaseParser:
    for parser in _PARSERS:
        if parser.supports(file_type):
            return parser
    raise ParseFailed(f"不支持的文件类型：{file_type}")


def parse_file(path: Path, file_type: str) -> ParseResult:
    return get_parser(file_type).parse(path)
