"""SessionEngine —— 会话编排层。见 docs/design.md §0/§1.2。

职责：持有 messages + abort，组 ToolContext，调 agent_loop，把每条消息写 transcript.jsonl，
逐事件 yield 给上层（CLI / 未来的 server SSE）。它不写具体 provider/tool 逻辑。
"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator, Awaitable, Callable

from core.abort import AbortSignal
from core.harness.approval import ApprovalMode
from core.loop import LoopEvent, agent_loop
from core.obs.tracer import ConsoleTracer
from core.tools.base import PermissionResult, Tool, ToolContext
from core.types import Message, TextBlock


async def _deny_all(_perm: PermissionResult) -> bool:
    return False  # fail-closed：没接审批回调时，需确认的操作一律拒绝


class SessionEngine:
    def __init__(
        self, *,
        provider: Any,
        tools: list[Tool],
        system: str,
        sandbox: Any,
        model: str,
        approval_mode: ApprovalMode = ApprovalMode.ASK,
        request_approval: Callable[[PermissionResult], Awaitable[bool]] | None = None,
        tracer: Any = None,
        transcript_path: str | None = None,
        cwd: str = ".",
        max_turns: int = 30,
    ):
        self.provider = provider
        self.tools = tools
        self.system = system
        self.sandbox = sandbox
        self.model = model
        self.approval_mode = approval_mode
        self.request_approval = request_approval or _deny_all
        self.tracer = tracer or ConsoleTracer()
        self.transcript_path = transcript_path
        self.cwd = cwd
        self.max_turns = max_turns
        self.messages: list[Message] = []
        self.abort = AbortSignal()

    def interrupt(self) -> None:
        self.abort.abort()

    async def submit(self, text: str) -> AsyncIterator[LoopEvent]:
        user_msg = Message(role="user", content=[TextBlock(text=text)])
        self.messages.append(user_msg)
        self._persist(user_msg)
        ctx = ToolContext(
            cwd=self.cwd, sandbox=self.sandbox, abort=self.abort, read_file_state={},
            approval_mode=self.approval_mode, request_approval=self.request_approval,
            tracer=self.tracer,
        )
        async for ev in agent_loop(
            messages=self.messages, system=self.system, provider=self.provider,
            tools=self.tools, ctx=ctx, model=self.model, max_turns=self.max_turns,
        ):
            if ev.message is not None:
                self._persist(ev.message)
            yield ev

    def _persist(self, msg: Message) -> None:
        if not self.transcript_path:
            return
        with open(self.transcript_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(msg.model_dump(), ensure_ascii=False) + "\n")
