"""bash 工具（非只读）。在沙箱内执行命令。见 docs/design.md §4.3。"""
from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel

from core.tools.base import BaseTool, ToolContext, ToolResult
from core.types import ToolResultBlock


class BashInput(BaseModel):
    cmd: str


class BashTool(BaseTool[BashInput]):
    """在沙箱内跑一条 bash 命令，返回 exit code 与输出。"""

    name = "bash"
    input_model = BashInput

    def is_read_only(self, inp: BashInput) -> bool:
        return False  # 默认按"可能有副作用"处理

    async def call(
        self, inp: BashInput, ctx: ToolContext, on_progress: Callable[[str], None]
    ) -> ToolResult:
        res = await ctx.sandbox.exec(["bash", "-lc", inp.cmd], cwd=ctx.cwd, timeout=60)
        output = (res.stdout + res.stderr).strip()
        if output:
            on_progress(output[:1000])
        return ToolResult(data={"exit_code": res.exit_code, "output": output})

    def to_model_result(self, data: Any, tool_use_id: str) -> ToolResultBlock:
        return ToolResultBlock(
            tool_use_id=tool_use_id,
            content=f"exit_code={data['exit_code']}\n{data['output']}",
            is_error=data["exit_code"] != 0,
        )
