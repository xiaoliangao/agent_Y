"""可运行 demo：用 MockProvider 驱动 agent_loop 建文件→读回→收尾。

跑：`python scripts/demo_loop.py`（无需 API key / Docker，用 LocalExecutor 在临时目录跑）。
这是"agent loop 真的在转"的最小可见证据。
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.abort import AbortSignal  # noqa: E402
from core.harness.approval import ApprovalMode  # noqa: E402
from core.loop import agent_loop  # noqa: E402
from core.obs.tracer import ConsoleTracer  # noqa: E402
from core.providers.mock import MockProvider, script_text, script_tool  # noqa: E402
from core.sandbox.local import LocalExecutor  # noqa: E402
from core.tools.base import ToolContext  # noqa: E402
from core.tools.bash import BashTool  # noqa: E402
from core.tools.read import ReadFileTool  # noqa: E402
from core.tools.write import WriteFileTool  # noqa: E402
from core.types import Message, TextBlock  # noqa: E402


def _text(msg: Message) -> str:
    return " ".join(b.text for b in msg.content if getattr(b, "type", "") == "text")


async def _auto_yes(_perm) -> bool:
    return True


async def main() -> None:
    root = tempfile.mkdtemp(prefix="agenty-demo-")
    print(f"workspace: {root}\n")
    ctx = ToolContext(
        cwd=".", sandbox=LocalExecutor(root), abort=AbortSignal(),
        read_file_state={}, approval_mode=ApprovalMode.AUTO,
        request_approval=_auto_yes, tracer=ConsoleTracer(),
    )
    provider = MockProvider([
        script_tool("我先建个文件。", "bash", {"cmd": "printf 'hello agent-y' > note.txt"}, "b1"),
        script_tool("再读回确认。", "read_file", {"path": "note.txt"}, "r1"),
        script_text("已创建并确认 note.txt，内容为 hello agent-y。"),
    ])
    tools = [WriteFileTool(), ReadFileTool(), BashTool()]
    messages = [Message(role="user", content=[TextBlock(text="建个 note.txt 写句话再读回")])]

    async for ev in agent_loop(
        messages=messages, system="你是 Agent Y。", provider=provider, tools=tools, ctx=ctx
    ):
        if ev.kind == "assistant":
            if t := _text(ev.message):
                print(f"🤖 {t}")
            for b in ev.message.content:
                if getattr(b, "type", "") == "tool_use":
                    print(f"   → 调用工具 {b.name}({b.input})")
        elif ev.kind == "tool_results":
            for b in ev.message.content:
                flag = "❌" if b.is_error else "✅"
                print(f"   {flag} 结果: {str(b.content)[:80]}")
        elif ev.kind == "done":
            print(f"\n🏁 done: {ev.reason}")

    print(f"\n落地文件内容: {(Path(root) / 'note.txt').read_text().strip()!r}")


if __name__ == "__main__":
    asyncio.run(main())
