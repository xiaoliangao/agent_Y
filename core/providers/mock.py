"""MockProvider —— 可编排的假 provider，用于离线测试 agent_loop（无需 API key）。

用法：传入"每轮要吐的 StreamEvent 列表"的脚本；每次 stream() 取下一段。
辅助函数 `script_tool` / `script_text` 帮你快速造常见脚本。
"""
from __future__ import annotations

from typing import AsyncIterator

from core.types import Message, StreamEvent, ToolUseBlock, Usage


class MockProvider:
    name = "mock"

    def __init__(self, scripts: list[list[StreamEvent]]):
        self._scripts = scripts
        self._i = 0

    async def stream(self, **_kwargs) -> AsyncIterator[StreamEvent]:
        if self._i >= len(self._scripts):
            # 脚本用完：默认收尾，防止死循环
            yield StreamEvent(type="message_done", usage=Usage(), stop_reason="end_turn")
            return
        events = self._scripts[self._i]
        self._i += 1
        for ev in events:
            yield ev

    def count_tokens(self, messages: list[Message]) -> int | None:
        return None


def script_tool(text: str, tool_name: str, tool_input: dict, tool_id: str = "t1") -> list[StreamEvent]:
    """一轮：说一句话 + 调一个工具。"""
    return [
        StreamEvent(type="text_delta", text=text),
        StreamEvent(type="tool_use", tool_use=ToolUseBlock(id=tool_id, name=tool_name, input=tool_input)),
        StreamEvent(type="message_done", usage=Usage(output_tokens=10), stop_reason="tool_use"),
    ]


def script_text(text: str) -> list[StreamEvent]:
    """一轮：只说话、不调工具（= 结束）。"""
    return [
        StreamEvent(type="text_delta", text=text),
        StreamEvent(type="message_done", usage=Usage(output_tokens=5), stop_reason="end_turn"),
    ]
