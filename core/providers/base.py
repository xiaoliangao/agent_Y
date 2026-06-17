"""LLMProvider 接口 —— loop 只依赖这个 Protocol，永不 import 具体 provider。

见 docs/design.md §4.2。加一家模型 = 写一个 adapter（anthropic.py / openai_compat.py），不动 loop。
"""
from __future__ import annotations

from typing import AsyncIterator, Protocol

from core.types import Message, StreamEvent


class ProviderError(Exception):
    """provider API 错误（限流/超时/鉴权）。不静默吞，由 loop 决定重试/上报。"""

    def __init__(self, code: str, message: str = "", retryable: bool = False):
        super().__init__(message or code)
        self.code = code
        self.retryable = retryable


class LLMProvider(Protocol):
    name: str

    async def stream(
        self,
        *,
        system: str,
        messages: list[Message],
        tools: list[dict],  # 每个 = tool.input_model.model_json_schema() 包装
        model: str,
        max_tokens: int,
        extra: dict | None = None,  # thinking/effort 等 provider 特有项
    ) -> AsyncIterator[StreamEvent]:
        """流式产出归一化事件。

        契约保证（见 design §4.2）：
          1. 顺序 (text_delta|thinking_delta|tool_use)* → message_done
          2. tool_use 仅在该块完整、input 已 json.loads 后吐出
          3. message_done 必带 usage 与 stop_reason（后者仅记录）
          4. abort → 停产、清理、抛 Aborted；API 错误 → 抛 ProviderError
        """
        ...

    def count_tokens(self, messages: list[Message]) -> int | None:
        """能精确就精确（对端 usage / tiktoken），否则 None 让 harness 粗估。"""
        ...
