"""LLM 客户端：多 provider 热切换、超时/重试、JSON 模式、熔断、token 埋点。

统一走 OpenAI 兼容协议（base_url + model），不绑定任何厂商。
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.adapters.mock.mock_llm import MockLLM
from app.core.config import settings
from app.core.exceptions import LLMTimeout, LLMUnavailable
from app.core.logging import get_logger

logger = get_logger(__name__)

PROVIDER_DEFAULTS = {
    "deepseek": ("https://api.deepseek.com/v1", "deepseek-chat"),
    "qwen": ("https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-max"),
    "glm": ("https://open.bigmodel.cn/api/paas/v4", "glm-4-plus"),
}


@dataclass
class LLMResult:
    text: str
    scene: str
    model: str
    prompt_ver: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    success: bool = True
    error: str | None = None
    cached: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class _CircuitBreaker:
    def __init__(self, threshold: int, cooldown: int) -> None:
        self.threshold = threshold
        self.cooldown = cooldown
        self.failures = 0
        self.open_until = 0.0

    def allow(self) -> bool:
        return time.time() >= self.open_until

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            self.open_until = time.time() + self.cooldown
            logger.warning("llm_circuit_open", failures=self.failures, cooldown=self.cooldown)

    def record_success(self) -> None:
        self.failures = 0
        self.open_until = 0.0

    @property
    def is_open(self) -> bool:
        return time.time() < self.open_until


class LLMClient:
    def __init__(self) -> None:
        self.provider = settings.LLM_PROVIDER.lower()
        self._mock = MockLLM()
        self._breaker = _CircuitBreaker(
            settings.LLM_CIRCUIT_FAILURE_THRESHOLD, settings.LLM_CIRCUIT_COOLDOWN_SECONDS
        )
        self._semaphore = asyncio.Semaphore(max(1, settings.LLM_CONCURRENCY))
        base, model = PROVIDER_DEFAULTS.get(self.provider, ("", ""))
        self.base_url = (settings.LLM_API_BASE or base).rstrip("/")
        self.model = settings.LLM_MODEL or model or "mock"
        if self.provider == "mock":
            self.model = "mock-llm"

    @property
    def is_mock(self) -> bool:
        return self.provider == "mock"

    def temperature_for(self, scene: str) -> float:
        if scene.startswith("grader"):
            return settings.LLM_TEMPERATURE_GRADE
        if scene.startswith("tutor"):
            return settings.LLM_TEMPERATURE_TUTOR
        return settings.LLM_TEMPERATURE_GEN

    async def chat(
        self,
        scene: str,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        json_mode: bool = False,
        meta: dict[str, Any] | None = None,
        prompt_ver: str | None = None,
    ) -> LLMResult:
        started = time.perf_counter()
        temp = self.temperature_for(scene) if temperature is None else temperature

        if self.is_mock:
            text = await self._mock.reply(scene, messages, meta)
            latency = int((time.perf_counter() - started) * 1000)
            result = LLMResult(
                text=text,
                scene=scene,
                model=self.model,
                prompt_ver=prompt_ver,
                prompt_tokens=sum(len(m.get("content", "")) for m in messages) // 2,
                completion_tokens=len(text) // 2,
                latency_ms=latency,
            )
            await self._audit(result)
            return result

        if not self._breaker.allow():
            raise LLMUnavailable("模型连续失败已熔断，请 60 秒后重试")

        last_error: Exception | None = None
        async with self._semaphore:
            for attempt in range(1, settings.LLM_MAX_RETRIES + 1):
                try:
                    payload: dict[str, Any] = {
                        "model": self.model,
                        "messages": messages,
                        "temperature": temp,
                        "stream": False,
                    }
                    if json_mode:
                        payload["response_format"] = {"type": "json_object"}
                    async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SECONDS) as client:
                        resp = await client.post(
                            f"{self.base_url}/chat/completions",
                            json=payload,
                            headers={
                                "Authorization": f"Bearer {settings.LLM_API_KEY}",
                                "Content-Type": "application/json",
                            },
                        )
                    if resp.status_code in (429, 500, 502, 503, 504):
                        raise httpx.HTTPStatusError(
                            f"LLM {resp.status_code}", request=resp.request, response=resp
                        )
                    resp.raise_for_status()
                    data = resp.json()
                    text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
                    usage = data.get("usage") or {}
                    result = LLMResult(
                        text=text,
                        scene=scene,
                        model=self.model,
                        prompt_ver=prompt_ver,
                        prompt_tokens=int(usage.get("prompt_tokens", 0)),
                        completion_tokens=int(usage.get("completion_tokens", 0)),
                        latency_ms=int((time.perf_counter() - started) * 1000),
                    )
                    self._breaker.record_success()
                    await self._audit(result)
                    return result
                except (httpx.TimeoutException, httpx.HTTPError) as exc:
                    last_error = exc
                    logger.warning("llm_call_failed", scene=scene, attempt=attempt, error=str(exc))
                    if attempt < settings.LLM_MAX_RETRIES:
                        await asyncio.sleep(min(2**attempt * 0.5, 5))

        assert last_error is not None
        self._breaker.record_failure()
        result = LLMResult(
            text="",
            scene=scene,
            model=self.model,
            latency_ms=int((time.perf_counter() - started) * 1000),
            success=False,
            error=str(last_error),
        )
        await self._audit(result)
        if isinstance(last_error, httpx.TimeoutException):
            raise LLMTimeout("模型响应超时")
        raise LLMUnavailable(f"模型调用失败：{last_error}")

    async def chat_json(
        self,
        scene: str,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        meta: dict[str, Any] | None = None,
        prompt_ver: str | None = None,
    ) -> tuple[dict[str, Any], LLMResult]:
        """结构化输出：JSON 模式 + json_repair 容错解析。"""
        result = await self.chat(
            scene, messages, temperature=temperature, json_mode=True, meta=meta,
            prompt_ver=prompt_ver,
        )
        return parse_json(result.text), result

    async def stream_chat(
        self,
        scene: str,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        meta: dict[str, Any] | None = None,
        prompt_ver: str | None = None,
    ):
        """流式输出（导学场景）。Mock 下按字符切片模拟打字机效果。"""
        started = time.perf_counter()
        temp = self.temperature_for(scene) if temperature is None else temperature

        if self.is_mock:
            full = await self._mock.reply(scene, messages, meta)
            step = 12
            for i in range(0, len(full), step):
                yield full[i : i + step]
                await asyncio.sleep(0.012)
            await self._audit(
                LLMResult(
                    text=full,
                    scene=scene,
                    model=self.model,
                    prompt_ver=prompt_ver,
                    prompt_tokens=sum(len(m.get("content", "")) for m in messages) // 2,
                    completion_tokens=len(full) // 2,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                )
            )
            return

        if not self._breaker.allow():
            raise LLMUnavailable("模型连续失败已熔断，请稍后重试")
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temp,
            "stream": True,
        }
        chunks: list[str] = []
        try:
            async with (
                httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SECONDS) as client,
                client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {settings.LLM_API_KEY}",
                        "Content-Type": "application/json",
                    },
                ) as resp,
            ):
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data in ("", "[DONE]"):
                        continue
                    try:
                        obj = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    delta = (
                        (obj.get("choices") or [{}])[0].get("delta", {}).get("content") or ""
                    )
                    if delta:
                        chunks.append(delta)
                        yield delta
            self._breaker.record_success()
            await self._audit(
                LLMResult(
                    text="".join(chunks),
                    scene=scene,
                    model=self.model,
                    prompt_ver=prompt_ver,
                    completion_tokens=len("".join(chunks)) // 2,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                )
            )
        except Exception as exc:
            self._breaker.record_failure()
            raise LLMUnavailable(f"流式输出失败：{exc}") from exc


    async def _audit(self, result: LLMResult) -> None:
        """写 llm_calls 表（论文性能数据来源）。使用独立短超时连接池，失败不影响主流程。"""
        try:
            from app.db.base import AuditSessionLocal
            from app.db.models import LLMCall

            async with AuditSessionLocal() as session:
                session.add(
                    LLMCall(
                        scene=result.scene,
                        model=result.model,
                        prompt_ver=result.prompt_ver,
                        prompt_tokens=result.prompt_tokens,
                        completion_tokens=result.completion_tokens,
                        total_tokens=result.total_tokens,
                        latency_ms=result.latency_ms,
                        success=result.success,
                        error=result.error,
                    )
                )
                await session.commit()
        except Exception as exc:
            logger.debug("llm_audit_skipped", error=str(exc))

    async def health(self) -> bool:
        if self.is_mock:
            return True
        if not settings.LLM_API_KEY:
            return False
        return not self._breaker.is_open


def parse_json(text: str) -> dict[str, Any]:
    """容错解析：剥离 markdown 围栏，截断 JSON 自动修复。"""
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start : end + 1]
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {"data": data}
    except json.JSONDecodeError:
        try:
            from json_repair import repair_json

            data = json.loads(repair_json(raw))
            return data if isinstance(data, dict) else {"data": data}
        except Exception:
            return {}


_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
