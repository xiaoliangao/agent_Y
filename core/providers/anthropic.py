"""AnthropicProvider —— Claude 原生适配器。见 docs/design.md §4.2。

惰性 import `anthropic`，把 Anthropic 的流式 SSE 翻译成统一 StreamEvent
（accumulate-then-finalize：tool_use 的 input 分片 JSON 累积、块结束才 parse，见 code-study-cc.md §1）。
翻译逻辑抽成 `translate_anthropic_stream` 纯函数，便于离线单测。

⚠️ 未用真 key 实测；结构按 anthropic SDK v0.40+ 与 claude-api 约定编写。
按约定：thinking={"type":"adaptive"} + output_config={"effort":...}，不传 temperature/top_p/budget_tokens。
M1 默认关 thinking（开启需 M2 处理 signature 回传）。
"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator

from core.types import Message, StreamEvent, ToolUseBlock, Usage


def _to_anthropic_messages(messages: list[Message]) -> list[dict]:
    """把内部 Message 转成 Anthropic messages 格式（M1 不回传 thinking——无 signature）。"""
    out: list[dict] = []
    for m in messages:
        content: list[dict] = []
        for b in m.content:
            if b.type == "text":
                content.append({"type": "text", "text": b.text})
            elif b.type == "tool_use":
                content.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
            elif b.type == "tool_result":
                content.append({
                    "type": "tool_result",
                    "tool_use_id": b.tool_use_id,
                    "content": b.content,
                    "is_error": b.is_error,
                })
            # thinking 块 M1 跳过
        if content:
            out.append({"role": m.role, "content": content})
    return out


async def translate_anthropic_stream(raw_events: Any) -> AsyncIterator[StreamEvent]:
    """Anthropic 原始流事件 → 统一 StreamEvent。raw_events 为 async 可迭代。"""
    input_tokens = 0
    output_tokens = 0
    stop_reason: str | None = None
    tool: dict | None = None  # 累积中的 tool_use 块

    async for ev in raw_events:
        etype = getattr(ev, "type", None)
        if etype == "message_start":
            usage = getattr(getattr(ev, "message", None), "usage", None)
            input_tokens = getattr(usage, "input_tokens", 0) or 0
        elif etype == "content_block_start":
            blk = getattr(ev, "content_block", None)
            if getattr(blk, "type", None) == "tool_use":
                tool = {"id": blk.id, "name": blk.name, "buf": ""}
        elif etype == "content_block_delta":
            d = getattr(ev, "delta", None)
            dtype = getattr(d, "type", None)
            if dtype == "text_delta":
                yield StreamEvent(type="text_delta", text=d.text)
            elif dtype == "thinking_delta":
                yield StreamEvent(type="thinking_delta", text=getattr(d, "thinking", ""))
            elif dtype == "input_json_delta" and tool is not None:
                tool["buf"] += d.partial_json
        elif etype == "content_block_stop":
            if tool is not None:
                try:
                    parsed = json.loads(tool["buf"] or "{}")
                except json.JSONDecodeError:
                    parsed = {}
                yield StreamEvent(
                    type="tool_use",
                    tool_use=ToolUseBlock(id=tool["id"], name=tool["name"], input=parsed),
                )
                tool = None
        elif etype == "message_delta":
            stop_reason = getattr(getattr(ev, "delta", None), "stop_reason", stop_reason)
            usage = getattr(ev, "usage", None)
            output_tokens = getattr(usage, "output_tokens", output_tokens) or output_tokens
        elif etype == "message_stop":
            yield StreamEvent(
                type="message_done",
                usage=Usage(input_tokens=input_tokens, output_tokens=output_tokens),
                stop_reason=stop_reason,
            )


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str | None = None, client: Any = None):
        self._client = client  # 可注入（测试）
        self._api_key = api_key

    def _get_client(self) -> Any:
        if self._client is None:
            from anthropic import AsyncAnthropic  # 惰性 import

            self._client = AsyncAnthropic(api_key=self._api_key)  # None → 读环境 ANTHROPIC_API_KEY
        return self._client

    async def stream(
        self, *, system: str, messages: list[Message], tools: list[dict],
        model: str, max_tokens: int, extra: dict | None = None,
    ) -> AsyncIterator[StreamEvent]:
        client = self._get_client()
        extra = extra or {}
        params: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": _to_anthropic_messages(messages),
        }
        if system:
            params["system"] = system
        if tools:
            params["tools"] = [
                {"name": t["name"], "description": t["description"], "input_schema": t["input_schema"]}
                for t in tools
            ]
        if extra.get("thinking"):  # 默认关；开启需 M2 处理 signature 回传
            params["thinking"] = {"type": "adaptive"}
        if extra.get("effort"):
            params["output_config"] = {"effort": extra["effort"]}

        raw = await client.messages.create(stream=True, **params)
        async for sev in translate_anthropic_stream(raw):
            yield sev

    def count_tokens(self, messages: list[Message]) -> int | None:
        return None  # M1：交给 harness 粗估
