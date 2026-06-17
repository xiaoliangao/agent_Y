"""OpenAICompatProvider —— OpenAI 兼容端点适配器（DeepSeek / GPT / 本地 Ollama·LM Studio）。

见 docs/design.md §4.2。惰性 import `openai` SDK，指 base_url 即可换端点。
把 OpenAI 风格的流式 delta（content + tool_calls 分片）翻译成统一 StreamEvent；
消息/工具在转换层从 Anthropic 风格转成 OpenAI 风格（tool_result → role:"tool"）。

翻译/转换抽成纯函数，便于离线单测（见 tests/test_openai_provider.py）。
"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator

from core.types import Message, StreamEvent, ToolUseBlock, Usage


def _to_openai_messages(system: str, messages: list[Message]) -> list[dict]:
    """内部 Message → OpenAI messages。tool_result 拆成 role:"tool" 消息。"""
    out: list[dict] = []
    if system:
        out.append({"role": "system", "content": system})
    for m in messages:
        if m.role == "user":
            tool_results = [b for b in m.content if b.type == "tool_result"]
            texts = [b.text for b in m.content if b.type == "text"]
            for b in tool_results:
                content = b.content if isinstance(b.content, str) else json.dumps(b.content, ensure_ascii=False)
                out.append({"role": "tool", "tool_call_id": b.tool_use_id, "content": content})
            if texts:
                out.append({"role": "user", "content": "\n".join(texts)})
            if not tool_results and not texts:
                out.append({"role": "user", "content": ""})
        else:  # assistant
            text = "".join(b.text for b in m.content if b.type == "text")
            tool_calls = [
                {
                    "id": b.id,
                    "type": "function",
                    "function": {"name": b.name, "arguments": json.dumps(b.input, ensure_ascii=False)},
                }
                for b in m.content
                if b.type == "tool_use"
            ]
            msg: dict = {"role": "assistant", "content": text or None}
            if tool_calls:
                msg["tool_calls"] = tool_calls
            out.append(msg)
    return out


def _to_openai_tools(tools: list[dict]) -> list[dict]:
    return [
        {"type": "function", "function": {
            "name": t["name"], "description": t["description"], "parameters": t["input_schema"]}}
        for t in tools
    ]


async def translate_openai_stream(chunks: Any) -> AsyncIterator[StreamEvent]:
    """OpenAI 流式 chunk → 统一 StreamEvent。tool_calls 按 index 累积、流末统一吐出。"""
    tool_accum: dict[int, dict] = {}
    usage: Usage | None = None
    finish_reason: str | None = None

    async for chunk in chunks:
        u = getattr(chunk, "usage", None)
        if u:
            usage = Usage(
                input_tokens=getattr(u, "prompt_tokens", 0) or 0,
                output_tokens=getattr(u, "completion_tokens", 0) or 0,
            )
        choices = getattr(chunk, "choices", None) or []
        if not choices:
            continue
        choice = choices[0]
        delta = getattr(choice, "delta", None)
        if delta is not None:
            content = getattr(delta, "content", None)
            if content:
                yield StreamEvent(type="text_delta", text=content)
            for tc in getattr(delta, "tool_calls", None) or []:
                idx = getattr(tc, "index", 0) or 0
                slot = tool_accum.setdefault(idx, {"id": None, "name": None, "args": ""})
                if getattr(tc, "id", None):
                    slot["id"] = tc.id
                fn = getattr(tc, "function", None)
                if fn is not None:
                    if getattr(fn, "name", None):
                        slot["name"] = fn.name
                    if getattr(fn, "arguments", None):
                        slot["args"] += fn.arguments
        if getattr(choice, "finish_reason", None):
            finish_reason = choice.finish_reason

    for idx in sorted(tool_accum):
        slot = tool_accum[idx]
        if not slot["name"]:
            continue
        try:
            parsed = json.loads(slot["args"] or "{}")
        except json.JSONDecodeError:
            parsed = {}
        yield StreamEvent(
            type="tool_use",
            tool_use=ToolUseBlock(id=slot["id"] or f"call_{idx}", name=slot["name"], input=parsed),
        )
    yield StreamEvent(type="message_done", usage=usage or Usage(), stop_reason=finish_reason)


class OpenAICompatProvider:
    name = "openai_compat"

    def __init__(self, api_key: str | None = None, base_url: str | None = None, client: Any = None):
        self._client = client
        self._api_key = api_key
        self._base_url = base_url

    def _get_client(self) -> Any:
        if self._client is None:
            from openai import AsyncOpenAI  # 惰性 import

            self._client = AsyncOpenAI(api_key=self._api_key, base_url=self._base_url)
        return self._client

    async def stream(
        self, *, system: str, messages: list[Message], tools: list[dict],
        model: str, max_tokens: int, extra: dict | None = None,
    ) -> AsyncIterator[StreamEvent]:
        client = self._get_client()
        params: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": _to_openai_messages(system, messages),
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            params["tools"] = _to_openai_tools(tools)
        chunks = await client.chat.completions.create(**params)
        async for sev in translate_openai_stream(chunks):
            yield sev

    def count_tokens(self, messages: list[Message]) -> int | None:
        return None
