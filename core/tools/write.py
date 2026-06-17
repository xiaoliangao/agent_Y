"""write_file 工具（写）。见 docs/design.md §4.3。"""
from __future__ import annotations

from typing import Callable

from pydantic import BaseModel

from core.tools.base import BaseTool, ToolContext, ToolResult


class WriteFileInput(BaseModel):
    path: str
    content: str


class WriteFileTool(BaseTool[WriteFileInput]):
    """把内容写入文件（覆盖）。路径相对 workspace。"""

    name = "write_file"
    input_model = WriteFileInput

    def is_read_only(self, inp: WriteFileInput) -> bool:
        return False

    async def call(
        self, inp: WriteFileInput, ctx: ToolContext, on_progress: Callable[[str], None]
    ) -> ToolResult:
        await ctx.sandbox.write_files({inp.path: inp.content.encode("utf-8")})
        return ToolResult(data=f"wrote {len(inp.content)} chars to {inp.path}")
