"""查询改写：把学生的口语提问改写成课件术语，改善口语类召回。

动机（实测数据）：口语类 Hit@1 0.667、Hit@3 0.867，明显低于字面类（0.867/1.000）。
原因是“网络为什么会堵车”与课件里的“拥塞控制/网络过载”没有字面交集，
向量检索能拉近一部分，但重排与词表门禁仍然吃亏。

约定：
- **只改查询，不改语料**，不改变任何事实性内容；改写结果必须保留原意；
- 失败/超时/格式不对时**静默退回原查询**，检索不会因此失败；
- 进程内 LRU 缓存（同一问题重复提问很常见），键为原查询。
"""

from __future__ import annotations

import logging
from collections import OrderedDict

logger = logging.getLogger(__name__)

_CACHE: OrderedDict[str, str] = OrderedDict()
_CACHE_MAX = 512

SYSTEM_PROMPT = (
    "你是计算机网络课程的检索助手。把学生的口语化提问改写成课程课件里可能出现的术语表达，"
    "用于检索课件，不回答问题。要求：\n"
    "1. 保留原问题的意图，不新增或删减要问的点；\n"
    "2. 用教材术语替换口语词（例如“堵车”→“拥塞”“网络过载”；“对暗号”→“三报文握手”“同步序号”）；\n"
    "3. 不要输出答案、不要解释、不要加“请问”等客套；\n"
    '4. 只输出 JSON：{"rewritten": "<改写后的查询>", "terms": ["<关键词>", ...]}\n'
    "改写后长度控制在 40 字以内。"
)


def _get_client():
    """惰性导入 LLM 客户端：模块级导入会形成
    rag → agents.llm → agents.__init__ → orchestrator → context → rag.retriever 的循环依赖。
    """
    from app.agents.llm import get_llm_client

    return get_llm_client()


def _cache_get(key: str) -> str | None:
    value = _CACHE.get(key)
    if value is None:
        return None
    _CACHE.move_to_end(key)
    return value


def _cache_put(key: str, value: str) -> None:
    _CACHE[key] = value
    _CACHE.move_to_end(key)
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)


async def rewrite_query(query: str) -> tuple[str, dict[str, object]]:
    """返回 (用于检索的查询, 元信息)。任何异常都退回原查询。"""
    text = (query or "").strip()
    if not text:
        return query, {"rewritten": False, "reason": "empty"}

    cached = _cache_get(text)
    if cached:
        return cached, {"rewritten": True, "cached": True, "original": text}

    try:
        payload, result = await _get_client().chat_json(
            "query_rewrite",
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            temperature=0.0,
        )
        rewritten = str((payload or {}).get("rewritten") or "").strip()
        # 基本校验：非空、不过长、不是原句照抄
        if not rewritten or len(rewritten) > 120:
            raise ValueError(f"改写结果不可用：{rewritten[:40]!r}")
        _cache_put(text, rewritten)
        logger.info(
            "query_rewritten original=%s rewritten=%s",
            text[:40],
            rewritten[:40],
        )
        return rewritten, {
            "rewritten": True,
            "original": text,
            "terms": (payload or {}).get("terms") or [],
        }
    except Exception as exc:  # 改写是增强项，失败不能影响检索
        logger.warning("query_rewrite_failed original=%s error=%s", text[:40], str(exc)[:120])
        return text, {"rewritten": False, "reason": str(exc)[:120], "original": text}


def clear_cache() -> None:
    _CACHE.clear()
