"""待办 / 提醒工具 —— 让助手能把「日程安排」真正写进用户的待办与提醒。

写 SQLite 调度库（不是文件系统），低风险、不走审批：用户让排日程，本就是要它写。
"""
from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel, Field

from core.tools.base import BaseTool, PermissionResult, ToolContext, ToolResult


class AddTodoInput(BaseModel):
    text: str = Field(description="待办内容")
    due: str | None = Field(default=None, description="可选日期/截止，如 2026-06-19 或 今天/明天")


class AddTodoTool(BaseTool):
    """把一件事加进用户的待办事项列表。"""

    name = "add_todo"
    input_model = AddTodoInput

    def __init__(self, scheduler: Any) -> None:
        self.scheduler = scheduler

    def is_read_only(self, inp: AddTodoInput) -> bool:
        return False

    async def check_permissions(self, inp: AddTodoInput, ctx: ToolContext) -> PermissionResult:
        return PermissionResult(behavior="allow", risk="low")

    async def call(self, inp: AddTodoInput, ctx: ToolContext, on_progress: Callable) -> ToolResult:
        self.scheduler.add_todo(inp.text, due=inp.due)
        return ToolResult(data=f"已加入待办：{inp.text}" + (f"（{inp.due}）" if inp.due else ""))


class AddReminderInput(BaseModel):
    text: str = Field(description="提醒内容")
    fire_at: str = Field(description="提醒时间，ISO 格式如 2026-06-19T15:00")
    repeat: str | None = Field(default=None, description="可选重复：daily / weekly")


class AddReminderTool(BaseTool):
    """设一个定时提醒（到点进提醒列表）。"""

    name = "add_reminder"
    input_model = AddReminderInput

    def __init__(self, scheduler: Any) -> None:
        self.scheduler = scheduler

    def is_read_only(self, inp: AddReminderInput) -> bool:
        return False

    async def check_permissions(self, inp: AddReminderInput, ctx: ToolContext) -> PermissionResult:
        return PermissionResult(behavior="allow", risk="low")

    async def call(self, inp: AddReminderInput, ctx: ToolContext, on_progress: Callable) -> ToolResult:
        self.scheduler.add_reminder(inp.text, inp.fire_at, repeat=inp.repeat)
        return ToolResult(data=f"已设提醒：{inp.text} @ {inp.fire_at}" + (f"（{inp.repeat}）" if inp.repeat else ""))
