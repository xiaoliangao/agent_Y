"""edit_file 工具（写，先读后写）。见 docs/design.md §4.3。

str_replace 语义：把 old_string 替换成 new_string。要求先 read_file 读过该文件、且 old_string 唯一。
"""
from __future__ import annotations

from typing import Callable

from pydantic import BaseModel

from core.tools.base import BaseTool, ToolContext, ToolResult, ValidationResult


class EditFileInput(BaseModel):
    path: str
    old_string: str
    new_string: str


class EditFileTool(BaseTool[EditFileInput]):
    """编辑文件：把 old_string 替换为 new_string。须先 read_file 读过该文件，且 old_string 在文件中唯一。"""

    name = "edit_file"
    input_model = EditFileInput

    def is_read_only(self, inp: EditFileInput) -> bool:
        return False

    async def validate_input(self, inp: EditFileInput, ctx: ToolContext) -> ValidationResult:
        if not ctx.read_file_state.get(inp.path):
            return ValidationResult(
                ok=False, message=f"必须先用 read_file 读过 {inp.path} 再编辑（先读后写）。"
            )
        if inp.old_string == inp.new_string:
            return ValidationResult(ok=False, message="old_string 与 new_string 相同，无改动。")
        return ValidationResult(ok=True)

    async def call(
        self, inp: EditFileInput, ctx: ToolContext, on_progress: Callable[[str], None]
    ) -> ToolResult:
        raw = await ctx.sandbox.read_file(inp.path)
        text = raw.decode("utf-8", "replace")
        count = text.count(inp.old_string)
        if count == 0:
            raise ValueError(f"old_string 未在 {inp.path} 中找到")
        if count > 1:
            raise ValueError(f"old_string 在 {inp.path} 出现 {count} 次，需唯一；请加更多上下文")
        new_text = text.replace(inp.old_string, inp.new_string, 1)
        await ctx.sandbox.write_files({inp.path: new_text.encode("utf-8")})
        return ToolResult(data=f"edited {inp.path} (1 replacement)")
