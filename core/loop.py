"""agent_loop —— 纯 act-observe 循环（异步生成器）。见 docs/design.md §1.2/§4。

心法（来自 code-study-cc.md §1 + OpenAI 文档双重佐证）：
  - **前进条件 = 本轮有没有 tool_use 块**，不看 stop_reason
  - 不是递归，是迭代 + 单点重组 messages
  - 错误即消息：工具失败回灌 is_error 的 tool_result，不抛异常中断 loop
  - 多重停止：无 tool_use(completed) / max_turns / abort

把 loop 写成异步生成器：yield 中间事件，最后 yield 一个 done 事件携带 reason
（正好对应 design §4.1.2 的 SSE `done` 事件）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncIterator

from core.tools.base import Tool, ToolContext
from core.tools.registry import run_tools
from core.types import Message, TextBlock, ThinkingBlock, ToolUseBlock, Usage


@dataclass
class LoopEvent:
    kind: str  # "assistant" | "tool_results" | "done"
    message: Message | None = None
    reason: str | None = None  # done 时：completed/max_turns/aborted/error


def tool_to_schema(tool: Tool) -> dict:
    return {
        "name": tool.name,
        "description": tool.description(),
        "input_schema": tool.input_model.model_json_schema(),
    }


async def _run_model_turn(
    provider: Any, system: str, messages: list[Message], tools_schema: list[dict],
    model: str, max_tokens: int, abort: Any,
) -> tuple[Message, list[ToolUseBlock], Usage | None]:
    """调一次模型，把流式事件累积成一条 assistant 消息 + 抽出 tool_use 块。"""
    text_parts: list[str] = []
    thinking_parts: list[str] = []
    tool_uses: list[ToolUseBlock] = []
    usage: Usage | None = None
    async for ev in provider.stream(
        system=system, messages=messages, tools=tools_schema, model=model, max_tokens=max_tokens
    ):
        if abort.aborted:
            break
        if ev.type == "text_delta":
            text_parts.append(ev.text or "")
        elif ev.type == "thinking_delta":
            thinking_parts.append(ev.text or "")
        elif ev.type == "tool_use" and ev.tool_use is not None:
            tool_uses.append(ev.tool_use)
        elif ev.type == "message_done":
            usage = ev.usage

    content: list = []
    if thinking_parts:
        content.append(ThinkingBlock(thinking="".join(thinking_parts)))
    if text_parts:
        content.append(TextBlock(text="".join(text_parts)))
    content.extend(tool_uses)
    if not content:  # 防御：空内容
        content.append(TextBlock(text=""))
    return Message(role="assistant", content=content), tool_uses, usage


async def agent_loop(
    *,
    messages: list[Message],
    system: str,
    provider: Any,
    tools: list[Tool],
    ctx: ToolContext,
    max_turns: int = 20,
    model: str = "default",
    max_tokens: int = 4096,
) -> AsyncIterator[LoopEvent]:
    """跑 act-observe 循环，逐事件 yield，最后 yield done(reason)。会就地累积 messages。"""
    tools_schema = [tool_to_schema(t) for t in tools]
    by_name = {t.name: t for t in tools}
    turn = 0
    while True:
        if ctx.abort.aborted:
            yield LoopEvent("done", reason="aborted")
            return

        assistant_msg, tool_uses, _usage = await _run_model_turn(
            provider, system, messages, tools_schema, model, max_tokens, ctx.abort
        )
        messages.append(assistant_msg)
        yield LoopEvent("assistant", message=assistant_msg)

        if not tool_uses:  # 唯一的"自然结束"信号：模型没要工具
            yield LoopEvent("done", reason="completed")
            return

        results = await run_tools(tool_uses, by_name, ctx)
        tr_msg = Message(role="user", content=list(results))
        messages.append(tr_msg)
        yield LoopEvent("tool_results", message=tr_msg)

        turn += 1
        if max_turns and turn >= max_turns:
            yield LoopEvent("done", reason="max_turns")
            return
