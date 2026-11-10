"""Prompt 模板注册表：模板存放在 .md 文件，代码只负责渲染与版本记录。"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from app.core.config import settings
from app.core.exceptions import NotFound

PROMPT_DIR = Path(__file__).resolve().parent
_PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")


class PromptTemplate:
    def __init__(self, name: str, version: str, text: str) -> None:
        self.name = name
        self.version = version
        self.text = text

    @property
    def variables(self) -> set[str]:
        return set(_PLACEHOLDER.findall(self.text))

    def render(self, **variables: object) -> str:
        missing = self.variables - set(variables)
        if missing:
            raise KeyError(f"Prompt {self.name}/{self.version} 缺少变量：{sorted(missing)}")

        def _sub(match: re.Match[str]) -> str:
            value = variables[match.group(1)]
            return "" if value is None else str(value)

        return _PLACEHOLDER.sub(_sub, self.text)


@lru_cache(maxsize=64)
def load(name: str, version: str | None = None) -> PromptTemplate:
    ver = version or settings.PROMPT_VERSION
    path = PROMPT_DIR / name / f"{ver}.md"
    if not path.exists():
        raise NotFound(f"Prompt 模板不存在：{name}/{ver}")
    return PromptTemplate(name, ver, path.read_text(encoding="utf-8"))


def render(name: str, version: str | None = None, **variables: object) -> str:
    return load(name, version).render(**variables)


def list_templates() -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for path in sorted(PROMPT_DIR.glob("*/*.md")):
        out.append({"name": path.parent.name, "version": path.stem})
    return out
