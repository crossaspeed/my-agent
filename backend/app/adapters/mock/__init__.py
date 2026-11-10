"""离线 Mock：LLM_PROVIDER=mock 时保证全链路可跑通。"""

from app.adapters.mock.mock_llm import MockLLM

__all__ = ["MockLLM"]
