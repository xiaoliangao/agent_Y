"""ContextManager：估算/阈值/工具结果清理/完整压缩/保留配对/熔断。见 design §5。"""
from __future__ import annotations

from core.harness.context import ContextManager, _strip_analysis, estimate_tokens
from core.providers.mock import MockProvider, script_text
from core.types import Message, TextBlock, ToolResultBlock, ToolUseBlock

_CLEARED = "[Old tool result content cleared]"


def _user(text: str) -> Message:
    return Message(role="user", content=[TextBlock(text=text)])


def _assistant_tool(tid: str) -> Message:
    return Message(role="assistant", content=[ToolUseBlock(id=tid, name="bash", input={"cmd": "ls"})])


def _tool_result(tid: str, content: str = "output") -> Message:
    return Message(role="user", content=[ToolResultBlock(tool_use_id=tid, content=content)])


def test_estimate_grows_with_text():
    assert estimate_tokens([_user("x" * 4000)]) > estimate_tokens([_user("hi")])


def test_thresholds():
    cm = ContextManager(context_window=100_000, max_output=4096)
    assert cm.effective == 100_000 - 4096
    assert cm.compact_trigger == cm.effective - 13_000
    assert cm.micro_trigger == int(cm.effective * 0.6)


def test_strip_analysis():
    assert _strip_analysis("<analysis>think</analysis><summary>S</summary>") == "S"
    assert _strip_analysis("<analysis>only</analysis> tail").strip() == "tail"
    assert _strip_analysis("no tags") == "no tags"


async def test_no_compact_when_small():
    cm = ContextManager(context_window=100_000)
    msgs = [_user("hi")]
    assert await cm.maybe_compact(msgs) is msgs  # 原样返回（同一对象）


async def test_micro_clears_old_tool_results():
    cm = ContextManager(context_window=1000, max_output=100)  # 无 provider → 只走 micro
    msgs: list[Message] = []
    for i in range(8):
        msgs.append(_assistant_tool(f"t{i}"))
        msgs.append(_tool_result(f"t{i}", content="R" * 200))
    out = await cm.maybe_compact(msgs)
    results = [b for m in out for b in m.content if getattr(b, "type", None) == "tool_result"]
    cleared = [b for b in results if b.content == _CLEARED]
    kept = [b for b in results if b.content != _CLEARED]
    assert len(kept) == 5 and len(cleared) == 3  # 保留最近 5，其余清理


async def test_full_compact_summarizes_head_keeps_tail():
    cm = ContextManager(
        provider=MockProvider([script_text("<analysis>x</analysis><summary>SUMMARY_HERE</summary>")]),
        model="mock", context_window=1000, max_output=100, transcript_path="/t.jsonl",
    )
    msgs = [_user("word " * 200) for _ in range(60)]  # 总量 >10k token，迫使保留尾部、摘要头部
    out = await cm.maybe_compact(msgs)
    assert out[0].role == "user"
    assert "SUMMARY_HERE" in out[0].content[0].text
    assert "transcript" in out[0].content[0].text
    assert 1 < len(out) < len(msgs)  # 头部被一条摘要替代


async def test_full_compact_keeps_tool_pair_intact():
    cm = ContextManager(
        provider=MockProvider([script_text("<summary>S</summary>")]),
        model="mock", context_window=1000, max_output=100,
    )
    # 头部一堆文本，尾部边界恰好是 tool_use/tool_result 配对
    msgs = [_user("word " * 200) for _ in range(40)]
    msgs += [_assistant_tool("tA"), _tool_result("tA", "word " * 200)]
    msgs += [_user("word " * 200) for _ in range(40)]
    out = await cm.maybe_compact(msgs)
    # 保留段里所有 tool_result 都能在前面找到配对的 tool_use（无孤立）
    seen_tool_use = {b.id for m in out for b in m.content if getattr(b, "type", None) == "tool_use"}
    orphan = [
        b for m in out for b in m.content
        if getattr(b, "type", None) == "tool_result" and b.tool_use_id not in seen_tool_use
    ]
    assert orphan == []


class _BadProvider:
    name = "bad"

    async def stream(self, **_kwargs):
        raise RuntimeError("boom")
        yield  # noqa: 让它是 async generator

    def count_tokens(self, _messages):
        return None


async def test_circuit_breaker_stops_after_3_failures():
    cm = ContextManager(provider=_BadProvider(), model="m", context_window=1000, max_output=100)
    msgs = [_user("word " * 200) for _ in range(60)]
    for _ in range(3):
        await cm.maybe_compact(msgs)  # 每次 full 失败 → failures++ → 退回 micro
    assert cm._failures == 3
    await cm.maybe_compact(msgs)  # 第 4 次：熔断，不再调 provider
    assert cm._failures == 3
