"""编码场景：工具集 + 系统提示。见 docs/design.md §4.6。

系统提示词风格参考 docs/CLAUDE-FABLE-5.md：简洁、少格式化、强调"自己用工具核实而非臆测"、
工具纪律清晰；并落实 research.md §C-17/§C-22 的 self-verify（测试真过才算完成）。
"""
from __future__ import annotations

from core.tools.bash import BashTool
from core.tools.edit import EditFileTool
from core.tools.read import ReadFileTool
from core.tools.write import WriteFileTool

CODING_SYSTEM_PROMPT = """你是 Agent Y 的编码助手，在一个隔离沙箱里通过工具完成编码任务。

工作方式：
- 先用 read_file / bash（如 ls、grep、cat）了解代码与失败原因，再动手改；不要臆测文件内容或测试结果。
- 用 edit_file 做精确改动（必须先 read_file 读过该文件）；新建文件用 write_file。
- 改完**务必用 bash 跑测试验证**（如 `python -m pytest -q`）；只有测试真的通过才算完成——绝不在没跑测试时声称已修好。
- 一步只做一件清楚的事；工具失败会把错误信息回灌给你，据此调整后重试。

风格：简洁直接、少废话、少用项目符号。完成后用一两句话说明改了什么、测试是否通过。"""


class CodingScenario:
    name = "coding"

    def tools(self) -> list:
        return [ReadFileTool(), WriteFileTool(), EditFileTool(), BashTool()]

    def system_prompt(self) -> str:
        return CODING_SYSTEM_PROMPT

    def skills_dir(self) -> str | None:
        return None
