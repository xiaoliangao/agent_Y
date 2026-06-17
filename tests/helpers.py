"""测试共用小工具。"""
from __future__ import annotations

from core.abort import AbortSignal
from core.harness.approval import ApprovalMode
from core.loop import agent_loop
from core.obs.tracer import ConsoleTracer
from core.sandbox.local import LocalExecutor
from core.tools.base import ToolContext
from core.types import Message, TextBlock


async def yes_(_perm) -> bool:
    return True


async def no_(_perm) -> bool:
    return False


def make_ctx(root, mode=ApprovalMode.AUTO, approve=yes_) -> ToolContext:
    return ToolContext(
        cwd=".", sandbox=LocalExecutor(str(root)), abort=AbortSignal(),
        read_file_state={}, approval_mode=mode, request_approval=approve, tracer=ConsoleTracer(),
    )


def user(text: str) -> list[Message]:
    return [Message(role="user", content=[TextBlock(text=text)])]


async def collect(messages, provider, tools, ctx, max_turns=15):
    return [
        ev
        async for ev in agent_loop(
            messages=messages, system="", provider=provider, tools=tools, ctx=ctx, max_turns=max_turns
        )
    ]
