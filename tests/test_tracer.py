"""Tracer：contextvars 自动嵌套 + Recording/Console/Null + build_tracer 回退 + 引擎埋点。"""
from __future__ import annotations

import asyncio
from io import StringIO

from core.engine import SessionEngine
from core.harness.approval import ApprovalMode
from core.obs.tracer import (
    ConsoleTracer,
    NullTracer,
    RecordingTracer,
    build_tracer,
    summarize,
)
from core.providers.mock import MockProvider, script_text, script_tool
from core.sandbox.local import LocalExecutor
from core.tools.write import WriteFileTool


def test_summarize():
    assert summarize("x" * 500, 50).endswith("…")
    assert summarize("hi") == "hi"


def test_recording_nesting_via_contextvars():
    tr = RecordingTracer()
    with tr.span("run", kind="run"):
        with tr.span("llm", kind="llm"):
            pass
        with tr.span("tool", kind="tool"):
            pass
    by = {s.name: s for s in tr.spans}
    assert by["run"].parent is None  # 顶层
    assert by["llm"].parent == by["run"].id
    assert by["tool"].parent == by["run"].id


def test_recording_latency_and_error():
    tr = RecordingTracer()
    try:
        with tr.span("boom"):
            raise ValueError("x")
    except ValueError:
        pass
    assert "ValueError" in tr.spans[0].error


async def test_parallel_spans_share_enclosing_parent():
    tr = RecordingTracer()

    async def child(name):
        with tr.span(name, kind="tool"):
            await asyncio.sleep(0.01)

    with tr.span("turn", kind="turn") as turn:
        await asyncio.gather(child("a"), child("b"))
    by = {s.name: s for s in tr.spans}
    assert by["a"].parent == turn.id and by["b"].parent == turn.id


def test_console_prints():
    buf = StringIO()
    tr = ConsoleTracer(out=buf)
    with tr.span("run", kind="run") as s:
        s.set(model="m")
    out = buf.getvalue()
    assert "run[run]" in out and "model=m" in out


def test_null_tracer_noop():
    with NullTracer().span("x") as s:
        s.set(a=1)  # 不抛即可


def test_build_tracer_fallback(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    assert isinstance(build_tracer(console=True), ConsoleTracer)
    assert isinstance(build_tracer(console=False), NullTracer)


async def test_engine_emits_run_turn_llm_tool_spans(tmp_path):
    tr = RecordingTracer()
    provider = MockProvider([
        script_tool("写", "write_file", {"path": "a.txt", "content": "hi"}, "t1"),
        script_text("好了"),
    ])
    engine = SessionEngine(
        provider=provider, tools=[WriteFileTool()], system="s",
        sandbox=LocalExecutor(str(tmp_path)), model="mock",
        approval_mode=ApprovalMode.AUTO, tracer=tr,
    )
    _ = [ev async for ev in engine.submit("写 a.txt")]
    kinds = {s.kind for s in tr.spans}
    assert {"run", "turn", "llm", "tool"} <= kinds
    # tool span 往上能回溯到顶层 run
    by_id = {s.id: s for s in tr.spans}
    cur = next(s for s in tr.spans if s.kind == "tool")
    while cur is not None and cur.kind != "run":
        cur = by_id.get(cur.parent)
    assert cur is not None and cur.kind == "run"
