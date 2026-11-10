"""引用校验与防幻觉（计划书 8.6，本课题核心创新点）。

三关：
1) ID 合法性：chunk_id 必须来自本次检索结果，页码/文档名以 DB 为准（服务端覆盖）。
2) 引文一致性：归一化后 quote 必须是原文子串；否则用最长公共子串比判定
   ≥ CITATION_FUZZY_THRESHOLD 视为轻微改写，用原文片段自动纠正。
3) 答案-证据支撑：由 LLM 自检（在出题图 score_quality 节点完成，此处只提供结构）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.rag.retriever import RetrievedChunk

logger = get_logger(__name__)

_FULLWIDTH = str.maketrans(
    "，。；：？！（）【】《》“”‘’、　", ",.;:?!()[]<>\"\"'' 、"
)
_SPACE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """去空白 + 全半角统一 + 小写，用于引文一致性判定。"""
    if not text:
        return ""
    return _SPACE.sub("", text.translate(_FULLWIDTH)).lower()


def lcs_ratio(quote: str, content: str) -> tuple[float, str]:
    """引文与原文的匹配度，返回比值与匹配到的原文片段。

    先取最长公共子串作为「主体匹配」；若不足，再在锚点附近取窗口做块级对齐，
    取两者的较大值 —— 模型插入连接词/漏字这类轻微改写只破坏单一子串，
    不应被整题丢弃，但引文最终仍会被替换成原文片段（见 verify_refs）。
    """
    q = normalize(quote)
    c = normalize(content)
    if not q or not c:
        return 0.0, ""
    matcher = SequenceMatcher(None, q, c, autojunk=False)
    match = matcher.find_longest_match(0, len(q), 0, len(c))
    if match.size == 0:
        return 0.0, ""
    anchor = c[match.b : match.b + match.size]
    ratio = match.size / len(q)
    start = max(0, match.b - len(q))
    end = min(len(c), match.b + match.size + len(q))
    window_matcher = SequenceMatcher(None, q, c[start:end], autojunk=False)
    window_ratio = sum(b.size for b in window_matcher.get_matching_blocks()) / len(q)
    if window_ratio > ratio:
        return min(1.0, window_ratio), anchor
    return ratio, anchor


def best_matching_span(content: str, quote: str, target_len: int | None = None) -> str:
    """在原文中定位与 quote 最相近的连续片段，用作自动纠正后的引文。"""
    q = normalize(quote)
    matcher = SequenceMatcher(None, q, normalize(content), autojunk=False)
    match = matcher.find_longest_match(0, len(q), 0, len(normalize(content)))
    length = target_len or max(40, min(len(quote) or 120, 200))
    if match.size == 0:
        return content[:length]
    # 归一化后索引与原文索引不一致，用最长公共子串文本在原文中定位
    anchor = normalize(content)[match.b : match.b + match.size]
    idx = content.find(anchor[: max(8, min(len(anchor), 20))])
    if idx < 0:
        idx = 0
    start = max(0, idx - 10)
    end = min(len(content), start + length)
    span = content[start:end].strip()
    return span or content[:length]


@dataclass
class VerifyOutcome:
    ok: bool
    reason: str | None = None
    refs: list[dict[str, Any]] = field(default_factory=list)
    fix_count: int = 0
    max_ratio: float = 0.0

    def to_quality(self) -> dict[str, Any]:
        return {
            "citation_ok": self.ok,
            "citation_fix_count": self.fix_count,
            "quote_match_ratio": round(self.max_ratio, 4),
        }


def verify_refs(
    refs: list[dict[str, Any]],
    available: dict[int, RetrievedChunk],
    threshold: float | None = None,
) -> VerifyOutcome:
    """校验单题的 source_refs；返回可回写 DB 的规范化引用列表。"""
    threshold = settings.CITATION_FUZZY_THRESHOLD if threshold is None else threshold
    if not refs:
        return VerifyOutcome(ok=False, reason="缺少溯源（每道题至少需要 1 条原文引用）")

    fixed: list[dict[str, Any]] = []
    fix_count = 0
    max_ratio = 0.0

    for raw in refs:
        try:
            chunk_id = int(raw.get("chunk_id"))
        except (TypeError, ValueError):
            return VerifyOutcome(ok=False, reason="chunk_id 非法")
        chunk = available.get(chunk_id)
        if chunk is None:
            return VerifyOutcome(ok=False, reason=f"chunk {chunk_id} 不在本次检索结果中（疑似编造）")
        quote = str(raw.get("quote") or "").strip()

        if not quote:
            return VerifyOutcome(ok=False, reason=f"chunk {chunk_id} 的引文为空")

        if normalize(quote) in normalize(chunk.content):
            ratio = 1.0
            matched_quote = quote
        else:
            ratio, _ = lcs_ratio(quote, chunk.content)
            if ratio >= threshold:
                matched_quote = best_matching_span(chunk.content, quote)
                fix_count += 1
            else:
                return VerifyOutcome(
                    ok=False,
                    reason=f"引文与原文不符（chunk {chunk_id} 匹配度 {ratio:.2f} < {threshold}）",
                    max_ratio=ratio,
                )
        max_ratio = max(max_ratio, ratio)
        fixed.append(
            {
                "chunk_id": chunk_id,
                # 元数据一律以 DB（检索结果来自 DB）为准，不信任模型输出
                "document_id": chunk.document_id,
                "document_name": chunk.document_name,
                "page_no": chunk.page_no,
                "slide_no": chunk.slide_no,
                "heading_path": chunk.heading_path,
                "quote": matched_quote[:400],
                "score": round(chunk.score, 4),
            }
        )

    return VerifyOutcome(ok=True, refs=fixed, fix_count=fix_count, max_ratio=max_ratio)


def citation_coverage(refs: list[dict[str, Any]]) -> int:
    return len({r.get("chunk_id") for r in refs if r.get("chunk_id")})
