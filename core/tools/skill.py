"""use_skill 工具（渐进披露）。见 docs/design.md §4.6。

系统提示里只列技能 (name + 一句话)；当某个技能与当前任务相关，agent 调 use_skill(name)
把该技能的完整正文（步骤/注意事项/惯例）加载进上下文，再照着做。只读、不走审批。
"""
from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel, Field

from core.tools.base import BaseTool, ToolContext, ToolResult, ValidationResult


class UseSkillInput(BaseModel):
    name: str = Field(description="要加载的技能名（来自系统提示「可用技能」清单）")


class UseSkillTool(BaseTool):
    """加载一个已保存技能的完整说明，按其步骤完成任务。"""

    name = "use_skill"
    input_model = UseSkillInput

    def __init__(self, store: Any) -> None:
        self.store = store

    def is_read_only(self, inp: UseSkillInput) -> bool:
        return True

    async def validate_input(self, inp: UseSkillInput, ctx: ToolContext) -> ValidationResult:
        if not inp.name.strip():
            return ValidationResult(ok=False, message="name 不能为空")
        return ValidationResult(ok=True)

    async def call(self, inp: UseSkillInput, ctx: ToolContext, on_progress: Callable) -> ToolResult:
        sk = self.store.get(inp.name)
        if sk is None:
            avail = ", ".join(s.name for s in self.store.list()) or "（无）"
            return ToolResult(data=f"没有名为「{inp.name}」的技能。可用技能：{avail}")
        head = f"# 技能：{sk.name}\n{sk.description}".rstrip()
        return ToolResult(data=f"{head}\n\n{sk.body}".strip())
