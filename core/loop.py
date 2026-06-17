"""agent_loop —— 纯 act-observe 循环（异步生成器）。见 docs/design.md §1.2/§4。

心法（来自 code-study-cc.md §1 + OpenAI 文档双重佐证）：
  - **前进条件 = 本轮有没有 tool_use 块**，不看 stop_reason
  - 不是递归，是迭代 + 单点重组 messages
  - 错误即消息：工具失败回灌 is_error 的 tool_result，不抛异常中断 loop
  - 多重停止：无 tool_use(completed) / max_turns / abort

事件流（token 级流式）：边收 provider 的 delta 边 yield `text_delta`/`thinking_delta`/`tool_use`，
turn 末再 yield 一条 `assistant`(累积好的整条消息，供持久化/续接判断)，最后 yield `done`。
text 已在 delta 阶段流出，故 `assistant` 事件不用于再次显示文本（避免重复）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable

from core.obs.tracer import summarize
from core.tools.base import Tool, ToolContext
from core.tools.registry import run_tools
from core.types import Message, TextBlock, ThinkingBlock, ToolUseBlock


def _assistant_text(msg: Message) -> str:
    return " ".join(b.text for b in msg.content if getattr(b, "type", None) == "text")


@dataclass
class LoopEvent:
    kind: str  # text_delta | thinking_delta | tool_use | assistant | tool_results | done
    message: Message | None = None
    text: str | None = None
    tool_use: ToolUseBlock | None = None
    reason: str | None = None  # done 时：completed/max_turns/aborted/error


def tool_to_schema(tool: Tool) -> dict:
    return {
        "name": tool.name,
        "description": tool.description(),
        "input_schema": tool.input_model.model_json_schema(),
    }


async def _stream_model_turn(
    provider: Any, system: str, messages: list[Message], tools_schema: list[dict],
    model: str, max_tokens: int, abort: Any,
) -> AsyncIterator[LoopEvent]:
    """调一次模型：边流式 yield delta/tool_use，turn 末 yield 累积好的 assistant 消息。"""
    text_parts: list[str] = []
    thinking_parts: list[str] = []
    tool_uses: list[ToolUseBlock] = []
    async for ev in provider.stream(
        system=system, messages=messages, tools=tools_schema, model=model, max_tokens=max_tokens
    ):
        if abort.aborted:
            break
        if ev.type == "text_delta":
            text_parts.append(ev.text or "")
            yield LoopEvent("text_delta", text=ev.text or "")
        elif ev.type == "thinking_delta":
            thinking_parts.append(ev.text or "")
            yield LoopEvent("thinking_delta", text=ev.text or "")
        elif ev.type == "tool_use" and ev.tool_use is not None:
            tool_uses.append(ev.tool_use)
            yield LoopEvent("tool_use", tool_use=ev.tool_use)
        # message_done：仅用于结束本轮流

    content: list = []
    if thinking_parts:
        content.append(ThinkingBlock(thinking="".join(thinking_parts)))
    if text_parts:
        content.append(TextBlock(text="".join(text_parts)))
    content.extend(tool_uses)
    if not content:
        content.append(TextBlock(text=""))
    yield LoopEvent("assistant", message=Message(role="assistant", content=content))


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
    on_before_turn: Callable[[list[Message]], Awaitable[list[Message]]] | None = None,
) -> AsyncIterator[LoopEvent]:
    """跑 act-observe 循环，逐事件 yield（含 token 级 delta），最后 yield done(reason)。就地累积 messages。

    on_before_turn：每轮调模型前的钩子（如上下文压缩），就地替换 messages 内容。
    """
    tools_schema = [tool_to_schema(t) for t in tools]
    by_name = {t.name: t for t in tools}
    turn = 0
    while True:
        if ctx.abort.aborted:
            yield LoopEvent("done", reason="aborted")
            return

        if on_before_turn is not None:
            messages[:] = await on_before_turn(messages)  # 就地替换，保持调用方引用有效

        with ctx.tracer.span("turn", kind="turn", n=turn) as turn_span:
            assistant_msg: Message | None = None
            tool_uses: list[ToolUseBlock] = []
            with ctx.tracer.span("llm", kind="llm", model=model) as llm_span:
                async for ev in _stream_model_turn(
                    provider, system, messages, tools_schema, model, max_tokens, ctx.abort
                ):
                    if ev.kind == "assistant" and ev.message is not None:
                        assistant_msg = ev.message
                        tool_uses = [b for b in ev.message.content if b.type == "tool_use"]
                        llm_span.set(
                            tools=len(tool_uses), output=summarize(_assistant_text(ev.message))
                        )
                    yield ev

            if assistant_msg is not None:
                messages.append(assistant_msg)

            if not tool_uses:  # 唯一的"自然结束"信号：模型没要工具
                yield LoopEvent("done", reason="completed")
                return

            results = await run_tools(tool_uses, by_name, ctx)
            tr_msg = Message(role="user", content=list(results))
            messages.append(tr_msg)
            turn_span.set(tools_run=len(results))
            yield LoopEvent("tool_results", message=tr_msg)

        turn += 1
        if max_turns and turn >= max_turns:
            yield LoopEvent("done", reason="max_turns")
            return
