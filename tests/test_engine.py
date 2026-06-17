"""SessionEngine 测试（MockProvider + LocalExecutor，离线）。"""
from __future__ import annotations

from core.engine import SessionEngine
from core.harness.approval import ApprovalMode
from core.providers.mock import MockProvider, script_text, script_tool
from core.sandbox.local import LocalExecutor
from core.tools.write import WriteFileTool


async def test_engine_runs_and_writes_transcript(tmp_path):
    provider = MockProvider([
        script_tool("写文件", "write_file", {"path": "hi.txt", "content": "yo"}, "t1"),
        script_text("好了"),
    ])
    tp = tmp_path / "transcript.jsonl"
    engine = SessionEngine(
        provider=provider, tools=[WriteFileTool()], system="sys",
        sandbox=LocalExecutor(str(tmp_path)), model="mock",
        approval_mode=ApprovalMode.AUTO, transcript_path=str(tp),
    )
    events = [ev async for ev in engine.submit("写 hi.txt")]
    assert [e.reason for e in events if e.kind == "done"] == ["completed"]
    assert (tmp_path / "hi.txt").read_text() == "yo"
    # transcript：user + assistant(tool_use) + user(tool_result) + assistant(text) ≥ 4 行
    assert len(tp.read_text().splitlines()) >= 4
    assert len(engine.messages) >= 4


async def test_engine_default_denies_when_no_approver(tmp_path):
    # approval_mode=ASK 且未接 request_approval → 写操作被 fail-closed 拒绝
    provider = MockProvider([
        script_tool("写", "write_file", {"path": "x.txt", "content": "y"}, "t1"),
        script_text("被拦"),
    ])
    engine = SessionEngine(
        provider=provider, tools=[WriteFileTool()], system="",
        sandbox=LocalExecutor(str(tmp_path)), model="mock", approval_mode=ApprovalMode.ASK,
    )
    events = [ev async for ev in engine.submit("写 x")]
    tr = next(e for e in events if e.kind == "tool_results")
    assert tr.message.content[0].is_error
    assert not (tmp_path / "x.txt").exists()
