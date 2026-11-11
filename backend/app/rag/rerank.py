"""重排（两阶段检索的第二阶段）：对召回候选做精排。

设计要点：
- **总开关在配置**（`RERANK_BACKEND=off|cross|llm`），调用点用 `use_rerank=True` 表达
  "本场景允许重排"。两者同时满足才生效，便于按场景取舍（出题/阅卷要质量，导学要首字延迟）。
- **两种后端**：
  - `cross`：本地交叉编码器（默认 `BAAI/bge-reranker-v2-m3`），query 与候选逐对打分，
    精度最好；CPU 推理是阻塞调用，必须丢到线程池，不能卡住事件循环。
  - `llm`：用系统已有的 LLM 做 listwise 打分，无需额外模型，但浪费一次生成调用。
- **失败必须降级**：模型缺失、依赖未装、LLM 超时都回退到"保持原 RRF 顺序"，
  重排是增强项，绝不能让检索整体失败。
"""

from __future__ import annotations

import asyncio
import math
import threading
from typing import Any, Protocol

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.logging import get_logger

logger = get_logger(__name__)


class RerankItem(Protocol):
    """被重排对象需要提供的最小接口（避免与 retriever 循环依赖）。"""

    chunk_id: int
    content: str
    relevance: float


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    z = math.exp(x)
    return z / (1.0 + z)


class BaseReranker:
    backend = "off"

    async def rerank(self, query: str, items: list[RerankItem], top_k: int) -> list[RerankItem]:
        return items[:top_k]


class NoopReranker(BaseReranker):
    """降级实现：保持召回顺序，只做截断。"""


class CrossEncoderReranker(BaseReranker):
    """本地交叉编码器重排（sentence-transformers CrossEncoder）。"""

    backend = "cross"

    def __init__(self) -> None:
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:  # pragma: no cover - 可选依赖
            raise AppError(
                "未安装 sentence-transformers，无法使用交叉编码器重排。"
                "请构建带 embedding 依赖的镜像，或改用 RERANK_BACKEND=llm",
                code=1008,
            ) from exc
        self._model = CrossEncoder(settings.RERANK_MODEL, max_length=512)

    def _predict(self, query: str, texts: list[str]) -> list[float]:
        pairs = [(query, text[: settings.RERANK_MAX_CHARS]) for text in texts]
        raw = self._model.predict(
            pairs, batch_size=settings.RERANK_BATCH_SIZE, show_progress_bar=False
        )
        return [_sigmoid(float(value)) for value in raw]

    async def rerank(self, query: str, items: list[RerankItem], top_k: int) -> list[RerankItem]:
        if not items:
            return []
        texts = [item.content for item in items]
        # CPU 推理是阻塞调用：放到线程池，避免阻塞 FastAPI 事件循环
        scores = await asyncio.to_thread(self._predict, query, texts)
        if max(scores) < settings.RERANK_MIN_INFORMATIVE_SCORE:
            # 模型对所有候选都不置可否（sigmoid ≈ 0.5），排序无信息量 → 保持召回顺序
            logger.info("rerank_uninformative", top=round(max(scores), 4), n=len(scores))
            for item, score in zip(items, scores, strict=False):
                item.rerank_score = round(score, 4)  # type: ignore[attr-defined]
            return items[:top_k]

        for item, score in zip(items, scores, strict=False):
            # 只写 rerank_score 用于排序，**不回写 relevance**：
            # 交叉编码器的 sigmoid 输出在"无关"样本上约为 0.5，若合进 relevance 会把
            # 所有候选顶到门禁阈值之上（实测使越界提问误纳率从 33% 升到 100%）。
            item.rerank_score = round(score, 4)  # type: ignore[attr-defined]
        ranked = sorted(items, key=lambda it: -(getattr(it, "rerank_score", 0.0) or 0.0))
        return ranked[:top_k]


_RERANK_LLM_PROMPT = """你是检索结果相关性评估员。给定一个查询和若干课程片段，请为每个片段打分。

查询：{query}

片段列表：
{candidates}

打分标准（0~1）：
- 1.0：片段直接回答了查询所问的概念
- 0.6~0.9：片段涉及同一主题，能作为部分依据
- 0.2~0.5：只有个别术语相同，主题不同
- 0.0~0.2：基本无关

只输出 JSON：{{"scores": [{{"id": 片段编号, "score": 分值}}]}}，不要输出其他内容。"""


class LLMReranker(BaseReranker):
    """用现有大模型做 listwise 打分（无额外模型依赖）。"""

    backend = "llm"

    async def rerank(self, query: str, items: list[RerankItem], top_k: int) -> list[RerankItem]:
        if not items:
            return []
        from app.agents.llm import get_llm_client

        lines = [
            f"[{i}] {item.content[: settings.RERANK_MAX_CHARS]}"
            for i, item in enumerate(items, start=1)
        ]
        prompt = _RERANK_LLM_PROMPT.format(query=query, candidates="\n\n".join(lines))
        try:
            # 注意：chat_json 返回 (解析后的 dict, LLMResult)，不是 dict 本身
            payload, _ = await get_llm_client().chat_json(
                "rerank", [{"role": "user", "content": prompt}], temperature=0.0
            )
            raw_scores = (payload or {}).get("scores") or []
            mapping = {
                int(entry["id"]): float(entry["score"])
                for entry in raw_scores
                if isinstance(entry, dict) and "id" in entry and "score" in entry
            }
        except Exception as exc:  # pragma: no cover - 网络/解析失败都降级
            logger.warning("rerank_llm_failed", error=str(exc)[:200])
            return items[:top_k]

        if not mapping:
            logger.warning("rerank_llm_empty", candidates=len(items))
            return items[:top_k]

        for index, item in enumerate(items, start=1):
            score = max(0.0, min(1.0, mapping.get(index, 0.0)))
            # 同上：重排分只用于排序，不参与 relevance 与门禁判定
            item.rerank_score = round(score, 4)  # type: ignore[attr-defined]
        ranked = sorted(items, key=lambda it: -(getattr(it, "rerank_score", 0.0) or 0.0))
        return ranked[:top_k]


_instance: BaseReranker | None = None
_instance_backend: str | None = None
_lock = threading.Lock()


def get_reranker() -> BaseReranker:
    """按配置返回重排器；初始化失败时降级为 Noop，不影响检索主流程。"""
    global _instance, _instance_backend
    backend = (settings.RERANK_BACKEND or "off").strip().lower()
    if backend in ("", "off", "none", "0", "false"):
        return NoopReranker()
    with _lock:
        if _instance is not None and _instance_backend == backend:
            return _instance
        try:
            if backend == "cross":
                _instance = CrossEncoderReranker()
            elif backend == "llm":
                _instance = LLMReranker()
            else:
                logger.warning("rerank_backend_unknown", backend=backend)
                _instance = NoopReranker()
        except AppError as exc:
            logger.warning("rerank_fallback", backend=backend, error=str(exc)[:200])
            _instance = NoopReranker()
        except Exception as exc:  # pragma: no cover - 模型损坏等
            logger.warning("rerank_init_failed", backend=backend, error=str(exc)[:200])
            _instance = NoopReranker()
        _instance_backend = backend
        return _instance


def reset_reranker() -> None:
    global _instance, _instance_backend
    with _lock:
        _instance = None
        _instance_backend = None


async def apply_rerank(
    query: str, items: list[RerankItem], top_k: int
) -> list[RerankItem]:
    """对候选做精排；任何异常都退化为原顺序，保证检索可用。"""
    if not items:
        return []
    reranker = get_reranker()
    if isinstance(reranker, NoopReranker):
        return items[:top_k]
    try:
        return await reranker.rerank(query, items, top_k)
    except Exception as exc:  # pragma: no cover - 兜底
        logger.warning("rerank_failed", backend=reranker.backend, error=str(exc)[:200])
        return items[:top_k]


def backend_name() -> str:
    return get_reranker().backend


def debug_info() -> dict[str, Any]:
    return {
        "configured": settings.RERANK_BACKEND,
        "active": backend_name(),
        "model": settings.RERANK_MODEL if settings.RERANK_BACKEND == "cross" else None,
        "candidates": settings.RERANK_CANDIDATES,
    }
