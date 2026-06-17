"""单轮文本补全助手。

给"小模型副任务"用：记忆挑选 / 反思沉淀 / 上下文压缩摘要。
禁工具、累积 text_delta 成一段字符串。只依赖 LLMProvider 协议（design §4.2）。
"""
from __future__ import annotations

from typing import Any

from core.types import Message


async def complete_text(
    provider: Any, *, system: str, messages: list[Message], model: str, max_tokens: int = 1024
) -> str:
    parts: list[str] = []
    async for ev in provider.stream(
        system=system, messages=messages, tools=[], model=model, max_tokens=max_tokens
    ):
        if ev.type == "text_delta" and ev.text:
            parts.append(ev.text)
    return "".join(parts)
