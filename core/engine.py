"""SessionEngine —— 会话编排层。见 docs/design.md §0/§1.2。

职责：持有 messages + abort，组 ToolContext，调 agent_loop，把每条消息写 transcript.jsonl，
逐事件 yield 给上层（CLI / 未来的 server SSE）。它不写具体 provider/tool 逻辑。
"""
from __future__ import annotations

import json
import time
from typing import Any, AsyncIterator, Awaitable, Callable

from core.abort import AbortSignal
from core.harness.approval import ApprovalMode
from core.loop import LoopEvent, agent_loop
from core.memory.recall import age_caveat, humanize_age
from core.memory.reflect import extract_memories
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
        context_manager: Any = None,
        memory_store: Any = None,
        reflect: bool = False,
        memory_recall_k: int = 5,
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
        self.context_manager = context_manager  # 可选：上下文压缩（每轮调模型前）
        self.memory_store = memory_store  # 可选：长期记忆（召回注入 + 反思沉淀）
        self.reflect = reflect  # 会话结束后是否提炼记忆
        self.memory_recall_k = memory_recall_k
        self.messages: list[Message] = []
        self.abort = AbortSignal()

    def interrupt(self) -> None:
        self.abort.abort()

    async def submit(self, text: str) -> AsyncIterator[LoopEvent]:
        user_msg = Message(role="user", content=[TextBlock(text=text)])
        self.messages.append(user_msg)
        self._persist(user_msg)
        system = await self._augment_system(text)
        ctx = ToolContext(
            cwd=self.cwd, sandbox=self.sandbox, abort=self.abort, read_file_state={},
            approval_mode=self.approval_mode, request_approval=self.request_approval,
            tracer=self.tracer,
        )
        on_before = self.context_manager.maybe_compact if self.context_manager is not None else None
        async for ev in agent_loop(
            messages=self.messages, system=system, provider=self.provider,
            tools=self.tools, ctx=ctx, model=self.model, max_turns=self.max_turns,
            on_before_turn=on_before,
        ):
            if ev.message is not None:
                self._persist(ev.message)
            yield ev
        await self._reflect()

    async def _augment_system(self, text: str) -> str:
        """把 MEMORY.md 索引 + 召回的相关记忆拼进 system（无 memory_store 则原样）。"""
        if self.memory_store is None:
            return self.system
        parts = [self.system]
        index = self.memory_store.load_index()
        if index.strip():
            parts.append("# 长期记忆索引 (MEMORY.md)\n" + index)
        try:
            recalled = await self.memory_store.recall(text, k=self.memory_recall_k)
        except Exception:
            recalled = []
        if recalled:
            now = time.time()
            blocks = [
                f'<memory name="{m.name}" age="{humanize_age(m.mtime, now)}">'
                f"{age_caveat(m.mtime, now)}\n{m.body}\n</memory>"
                for m in recalled
            ]
            parts.append("# 召回的相关记忆\n" + "\n".join(blocks))
        return "\n\n".join(parts)

    async def _reflect(self) -> None:
        """会话结束后提炼记忆（失败不影响主流程）。"""
        if self.memory_store is None or not self.reflect:
            return
        try:
            await extract_memories(self.memory_store, self.provider, self.model, self.messages)
        except Exception:
            pass

    def _persist(self, msg: Message) -> None:
        if not self.transcript_path:
            return
        with open(self.transcript_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(msg.model_dump(), ensure_ascii=False) + "\n")
