"""agent_loop 端到端测试：MockProvider 驱动，LocalExecutor 真写/读文件。

覆盖：调工具→回灌→停止、多工具串联、审批拒绝、只读模式拦写、max_turns、未知工具报错。
"""
from __future__ import annotations

from core.abort import AbortSignal
from core.harness.approval import ApprovalMode
from core.loop import agent_loop
from core.obs.tracer import ConsoleTracer
from core.providers.mock import MockProvider, script_text, script_tool
from core.sandbox.local import LocalExecutor
from core.tools.base import ToolContext
from core.tools.bash import BashTool
from core.tools.read import ReadFileTool
from core.tools.write import WriteFileTool
from core.types import Message, TextBlock


async def _yes(_perm) -> bool:
    return True


async def _no(_perm) -> bool:
    return False


def _ctx(root, mode=ApprovalMode.AUTO, approve=_yes) -> ToolContext:
    return ToolContext(
        cwd=".", sandbox=LocalExecutor(str(root)), abort=AbortSignal(),
        read_file_state={}, approval_mode=mode, request_approval=approve,
        tracer=ConsoleTracer(),
    )


async def _collect(messages, provider, tools, ctx, max_turns=10):
    return [
        ev
        async for ev in agent_loop(
            messages=messages, system="", provider=provider, tools=tools,
            ctx=ctx, max_turns=max_turns,
        )
    ]


def _user(text: str) -> list[Message]:
    return [Message(role="user", content=[TextBlock(text=text)])]


async def test_loop_writes_file(tmp_path):
    provider = MockProvider([
        script_tool("我来写文件", "write_file", {"path": "hello.txt", "content": "hi"}, "t1"),
        script_text("已写好 hello.txt"),
    ])
    msgs = _user("写个 hello.txt")
    events = await _collect(msgs, provider, [WriteFileTool(), ReadFileTool(), BashTool()], _ctx(tmp_path))
    assert [e.reason for e in events if e.kind == "done"] == ["completed"]
    assert (tmp_path / "hello.txt").read_text() == "hi"
    # messages 累积：user, assistant(tool_use), user(tool_result), assistant(text)
    assert len(msgs) == 4 and msgs[-1].role == "assistant"


async def test_loop_bash_then_read(tmp_path):
    provider = MockProvider([
        script_tool("建文件", "bash", {"cmd": "printf data > out.txt"}, "b1"),
        script_tool("读它", "read_file", {"path": "out.txt"}, "r1"),
        script_text("内容是 data"),
    ])
    events = await _collect(_user("建个文件再读"), provider, [WriteFileTool(), ReadFileTool(), BashTool()], _ctx(tmp_path))
    assert [e.reason for e in events if e.kind == "done"] == ["completed"]
    assert (tmp_path / "out.txt").read_text() == "data"


async def test_write_denied_when_user_says_no(tmp_path):
    provider = MockProvider([
        script_tool("我来写", "write_file", {"path": "x.txt", "content": "y"}, "t1"),
        script_text("好的，不写了"),
    ])
    events = await _collect(_user("写 x"), provider, [WriteFileTool()], _ctx(tmp_path, ApprovalMode.ASK, _no))
    assert [e.reason for e in events if e.kind == "done"] == ["completed"]
    assert not (tmp_path / "x.txt").exists()
    tr = next(e for e in events if e.kind == "tool_results")
    assert tr.message.content[0].is_error


async def test_read_only_mode_denies_write(tmp_path):
    provider = MockProvider([
        script_tool("写", "write_file", {"path": "x.txt", "content": "y"}, "t1"),
        script_text("被拦了"),
    ])
    events = await _collect(_user("写 x"), provider, [WriteFileTool()], _ctx(tmp_path, ApprovalMode.READ_ONLY))
    tr = next(e for e in events if e.kind == "tool_results")
    assert tr.message.content[0].is_error
    assert not (tmp_path / "x.txt").exists()


async def test_max_turns(tmp_path):
    (tmp_path / "p").write_text("x")
    provider = MockProvider([script_tool("a", "read_file", {"path": "p"}, f"t{i}") for i in range(50)])
    events = await _collect(_user("loop"), provider, [ReadFileTool()], _ctx(tmp_path), max_turns=3)
    assert [e.reason for e in events if e.kind == "done"] == ["max_turns"]


async def test_unknown_tool_returns_error(tmp_path):
    provider = MockProvider([
        script_tool("调不存在的", "nope", {}, "t1"),
        script_text("ok"),
    ])
    events = await _collect(_user("x"), provider, [ReadFileTool()], _ctx(tmp_path))
    tr = next(e for e in events if e.kind == "tool_results")
    assert tr.message.content[0].is_error
    assert "unknown tool" in tr.message.content[0].content


async def test_abort_stops_loop(tmp_path):
    provider = MockProvider([script_tool("a", "read_file", {"path": "p"}, "t1")])
    ctx = _ctx(tmp_path)
    ctx.abort.abort()  # 开局就中断
    events = await _collect(_user("x"), provider, [ReadFileTool()], ctx)
    assert [e.reason for e in events if e.kind == "done"] == ["aborted"]
