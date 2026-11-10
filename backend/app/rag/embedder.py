"""Embedding 后端抽象与三种实现。

- HashEmbedder：离线零依赖，字符 n-gram + 词级哈希（稳定、可复现，用于开发和单测）
- ApiEmbedder：OpenAI 兼容 /embeddings（BGE-M3、text-embedding-v3 等）
- LocalEmbedder：sentence-transformers 本地加载 BGE-M3

切换 embedding 模型必须重建集合（EMBEDDING_DIM 变化），系统提供 reindex 接口。
"""

from __future__ import annotations

import hashlib
import re
from abc import ABC, abstractmethod
from functools import lru_cache

import numpy as np

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.logging import get_logger

logger = get_logger(__name__)

_WORD = re.compile(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]")


def _stable_index(token: str, dim: int, salt: str = "") -> int:
    digest = hashlib.blake2b((salt + token).encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % dim


def _stable_sign(token: str) -> float:
    digest = hashlib.blake2b(("sign:" + token).encode("utf-8"), digest_size=2).digest()
    return 1.0 if digest[0] & 1 else -1.0


def tokenize_embed(text: str) -> list[str]:
    """字符 n-gram（中文）+ 英文词，兼顾中文短语的局部顺序信息。"""
    text = text.lower()
    words = _WORD.findall(text)
    grams: list[str] = list(words)
    for n in (2, 3):
        for i in range(len(words) - n + 1):
            grams.append("".join(words[i : i + n]))
    return grams


class BaseEmbedder(ABC):
    provider: str = "base"

    def __init__(self, dim: int) -> None:
        self.dim = dim

    @abstractmethod
    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]:
        vectors = await self.embed_documents([text])
        return vectors[0]

    async def health(self) -> bool:
        return True


class HashEmbedder(BaseEmbedder):
    provider = "hash"

    def __init__(self, dim: int | None = None) -> None:
        super().__init__(dim or settings.EMBEDDING_DIM)

    def _embed_one(self, text: str) -> list[float]:
        vec = np.zeros(self.dim, dtype=np.float32)
        tokens = tokenize_embed(text)
        if not tokens:
            return vec.tolist()
        counts: dict[str, int] = {}
        for token in tokens:
            counts[token] = counts.get(token, 0) + 1
        for token, count in counts.items():
            weight = 1.0 + np.log(count)  # 次线性 TF
            idx = _stable_index(token, self.dim)
            vec[idx] += _stable_sign(token) * weight
        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec /= norm
        return vec.tolist()

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]


class ApiEmbedder(BaseEmbedder):
    provider = "api"

    def __init__(self) -> None:
        super().__init__(settings.EMBEDDING_DIM)
        if not settings.EMBEDDING_API_BASE:
            raise AppError("EMBEDDING_API_BASE 未配置，无法使用 api 后端", code=1006)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        import httpx

        url = settings.EMBEDDING_API_BASE.rstrip("/") + "/embeddings"
        headers = {"Content-Type": "application/json"}
        if settings.EMBEDDING_API_KEY:
            headers["Authorization"] = f"Bearer {settings.EMBEDDING_API_KEY}"
        out: list[list[float]] = []
        batch = settings.EMBEDDING_BATCH_SIZE
        async with httpx.AsyncClient(timeout=60) as client:
            for i in range(0, len(texts), batch):
                payload = {"model": settings.EMBEDDING_MODEL, "input": texts[i : i + batch]}
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()["data"]
                data.sort(key=lambda d: d.get("index", 0))
                out.extend([d["embedding"] for d in data])
        if out and len(out[0]) != self.dim:
            raise AppError(
                f"Embedding 维度不匹配：配置 {self.dim}，返回 {len(out[0])}。"
                "请修正 EMBEDDING_DIM 并重建索引",
                code=1007,
            )
        return out


class LocalEmbedder(BaseEmbedder):
    provider = "local"

    def __init__(self) -> None:
        super().__init__(settings.EMBEDDING_DIM)
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - 可选依赖
            raise AppError(
                "未安装 sentence-transformers，无法使用本地 embedding。"
                "请 pip install '.[embedding]' 或改用 EMBEDDING_PROVIDER=hash/api",
                code=1008,
            ) from exc
        self._model = SentenceTransformer(settings.EMBEDDING_MODEL)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        import asyncio

        def _run() -> list[list[float]]:
            arr = self._model.encode(
                texts, batch_size=settings.EMBEDDING_BATCH_SIZE, normalize_embeddings=True
            )
            return np.asarray(arr, dtype=np.float32).tolist()

        return await asyncio.to_thread(_run)


@lru_cache(maxsize=4)
def get_embedder() -> BaseEmbedder:
    provider = settings.EMBEDDING_PROVIDER.lower()
    try:
        if provider == "api":
            return ApiEmbedder()
        if provider == "local":
            return LocalEmbedder()
    except AppError as exc:
        logger.warning("embedder_fallback", provider=provider, error=str(exc))
    return HashEmbedder()


def reset_embedder() -> None:
    get_embedder.cache_clear()
