"""read_file 工具（只读）。见 docs/design.md §4.3。"""
from __future__ import annotations

from typing import Callable

from pydantic import BaseModel

from core.tools.base import BaseTool, ToolContext, ToolResult


class ReadFileInput(BaseModel):
    path: str


class ReadFileTool(BaseTool[ReadFileInput]):
    """读取文件内容（相对 workspace）。"""

    name = "read_file"
    input_model = ReadFileInput

    def is_read_only(self, inp: ReadFileInput) -> bool:
        return True

    async def call(
        self, inp: ReadFileInput, ctx: ToolContext, on_progress: Callable[[str], None]
    ) -> ToolResult:
        data = await ctx.sandbox.read_file(inp.path)
        text = data.decode("utf-8", "replace")
        ctx.read_file_state[inp.path] = True  # 供 edit 工具"先读后写"校验
        return ToolResult(data=text)
