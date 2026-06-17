"""子 Agent 工具（spawn_agent）。见 docs/design.md §4 / PRD F2.4。

orchestrator 把一个可独立完成的子任务派给子 agent：**隔离的子上下文**（全新 messages），
复用同一 provider/model + 一组工具（不含 spawn 自身，防递归），跑一轮 act-observe，结论回传父级。
"""
from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel, Field

from core.tools.base import BaseTool, PermissionResult, ToolContext, ToolResult


class SpawnAgentInput(BaseModel):
    task: str = Field(description="交给子 agent 独立完成的子任务（自包含、说清目标）")


class SpawnAgentTool(BaseTool):
    """派生一个子 agent 处理一个独立子任务（隔离上下文），返回它的结论。

    适合把一个能自包含完成的子任务（如"在这些文件里查清 X"）交给它，避免污染主对话上下文。
    """

    name = "spawn_agent"
    input_model = SpawnAgentInput

    def __init__(self, *, provider: Any, model: str, tools: list, system: str, max_turns: int = 12):
        self.provider = provider
        self.model = model
        self.tools = tools  # 子 agent 可用工具（不含 spawn_agent，防递归）
        self.system = system
        self.max_turns = max_turns

    def is_read_only(self, inp: SpawnAgentInput) -> bool:
        return False

    async def check_permissions(self, inp: SpawnAgentInput, ctx: ToolContext) -> PermissionResult:
        return PermissionResult(behavior="allow", risk="low")  # 子 agent 内部工具各自再审批

    async def call(self, inp: SpawnAgentInput, ctx: ToolContext, on_progress: Callable) -> ToolResult:
        from core.loop import agent_loop
        from core.types import Message, TextBlock

        # 隔离子上下文：复用 sandbox/审批/中断，但全新 read_file_state
        sub_ctx = ToolContext(
            cwd=ctx.cwd, sandbox=ctx.sandbox, abort=ctx.abort, read_file_state={},
            approval_mode=ctx.approval_mode, request_approval=ctx.request_approval, tracer=ctx.tracer,
        )
        messages = [Message(role="user", content=[TextBlock(text=inp.task)])]
        final = ""
        async for ev in agent_loop(
            messages=messages, system=self.system, provider=self.provider, tools=self.tools,
            ctx=sub_ctx, model=self.model, max_turns=self.max_turns,
        ):
            if ev.kind == "assistant" and ev.message is not None:
                text = " ".join(
                    b.text for b in ev.message.content if getattr(b, "type", None) == "text"
                ).strip()
                if text:
                    final = text  # 末条非空助手文本即子 agent 结论
        return ToolResult(data=final or "(子 agent 无输出)")
