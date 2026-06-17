"""核心数据类型。归一化到 Anthropic 风格 content blocks。见 docs/design.md §3。

这是全局共享的"语言"：providers/tools/loop/engine 都用这些类型对话。
OpenAI 等格式在各自 provider adapter 层转换成这里的形状。
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


# ---------- 内容块（content blocks）----------
class TextBlock(BaseModel):
    type: Literal["text"] = "text"
    text: str


class ThinkingBlock(BaseModel):
    type: Literal["thinking"] = "thinking"
    thinking: str


class ToolUseBlock(BaseModel):
    type: Literal["tool_use"] = "tool_use"
    id: str
    name: str
    input: dict[str, Any]


class ToolResultBlock(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: str | list[dict]  # 文本或多模态
    is_error: bool = False


ContentBlock = TextBlock | ThinkingBlock | ToolUseBlock | ToolResultBlock


# ---------- 消息 ----------
class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: list[ContentBlock]


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    # 可扩展 cache_read / cache_write


# ---------- 归一化的流式事件（provider → loop）----------
class StreamEvent(BaseModel):
    """provider 与 loop 之间的契约（见 design §3/§4.2）。

    adapter 必须保证：tool_use 块完整、input 已 json.loads 后才作为一个
    `tool_use` 事件吐出；message_done 必带 usage + stop_reason。
    """

    type: Literal["text_delta", "thinking_delta", "tool_use", "message_done"]
    text: str | None = None
    tool_use: ToolUseBlock | None = None
    usage: Usage | None = None
    stop_reason: str | None = None  # 仅记录/调试，不作为停止主信号
