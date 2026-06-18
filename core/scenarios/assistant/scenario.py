"""个人助手场景：工具集 + 系统提示。见 docs/design.md §4.6（M5）。

文件问答 + 办公文档 + 起草，全部在用户授权目录内操作（FolderAccess，§5.2）。
"""
from __future__ import annotations

from core.harness.fs_access import FolderAccess
from core.tools.assistant import (
    DocxWriteTool,
    DraftTool,
    PptxBuildTool,
    ReadDirTool,
    SearchFilesTool,
    SummarizeFilesTool,
    XlsxWriteTool,
)
from core.tools.web import WebFetchTool, WebSearchTool

ASSISTANT_SYSTEM_PROMPT = """你是 Agent Y 的个人助手，帮用户处理日常事务：文件问答、整理、起草、生成办公文档。

工作方式：
- 你只能访问用户**显式授权的目录**；用 read_dir / search_files / summarize_files 查看文件后再回答，不要臆测文件内容。
- 需要最新/外部信息时用 web_search 检索、web_fetch 取网页；回答时**引用来源**（文件名、行、或链接）。
- 生成办公文档用 xlsx_write / docx_write / pptx_build；写文件是越权操作，会先请用户确认。
- 起草邮件/周报/文档用 draft（纯文本，用户审阅后自行使用）。
- 用户让安排日程/记事/提醒时，用 add_todo 加进待办、add_reminder 设定时提醒（别只口头答应，要真写进去）。
- 一步只做一件清楚的事；工具失败会把错误回灌给你，据此调整。

风格：简洁直接、少废话。完成后用一两句话说明做了什么、产物在哪。"""


class AssistantScenario:
    name = "assistant"

    def __init__(self, fs: FolderAccess) -> None:
        self.fs = fs

    def tools(self) -> list:
        return [
            ReadDirTool(self.fs),
            SearchFilesTool(self.fs),
            SummarizeFilesTool(self.fs),
            WebSearchTool(),
            WebFetchTool(),
            DraftTool(),
            XlsxWriteTool(self.fs),
            DocxWriteTool(self.fs),
            PptxBuildTool(self.fs),
        ]

    def system_prompt(self) -> str:
        return ASSISTANT_SYSTEM_PROMPT

    def skills_dir(self) -> str | None:
        return None
