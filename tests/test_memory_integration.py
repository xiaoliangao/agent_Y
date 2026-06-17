"""SessionEngine 接线 memory + context（opt-in）的集成测试。"""
from __future__ import annotations

from typing import AsyncIterator

from core.engine import SessionEngine
from core.harness.context import ContextManager
from core.memory.store import FileMemoryStore, Memory
from core.providers.mock import MockProvider, script_text
from core.types import StreamEvent


class CapturingProvider:
    """记录每次 stream 收到的 system，便于断言记忆是否注入。"""

    name = "cap"

    def __init__(self, events: list[StreamEvent]):
        self._events = events
        self.systems: list[str] = []

    async def stream(self, *, system, messages, tools, model, max_tokens, extra=None) -> AsyncIterator[StreamEvent]:
        self.systems.append(system)
        for ev in self._events:
            yield ev

    def count_tokens(self, _messages):
        return None


async def test_engine_injects_recalled_memory_into_system(tmp_path):
    store = FileMemoryStore(str(tmp_path / "mem"))
    await store.write(Memory(name="user-name", description="用户叫小亮", type="user", body="用户名字是小亮"))

    async def picker(query, candidates, k):  # 确定性挑选，避开关键词/LLM
        return ["user-name"]

    store._picker = picker
    cap = CapturingProvider(script_text("好的"))
    engine = SessionEngine(
        provider=cap, tools=[], system="基础提示", sandbox=None, model="mock", memory_store=store
    )
    _ = [ev async for ev in engine.submit("我叫什么")]
    assert any("小亮" in s for s in cap.systems)  # 召回的记忆正文进了 system
    assert any("MEMORY.md" in s for s in cap.systems)  # 索引也注入


async def test_engine_reflect_writes_memory(tmp_path):
    store = FileMemoryStore(str(tmp_path / "mem"))
    provider = MockProvider([
        script_text("任务完成"),  # loop 的一轮（无工具 → completed）
        script_text('[{"name":"likes-x","description":"用户喜欢 X","type":"user","body":"X"}]'),  # reflect 调用
    ])
    engine = SessionEngine(
        provider=provider, tools=[], system="s", sandbox=None, model="mock",
        memory_store=store, reflect=True,
    )
    _ = [ev async for ev in engine.submit("记住我喜欢 X")]
    assert (tmp_path / "mem" / "likes-x.md").exists()
    assert "likes-x.md" in store.load_index()


async def test_engine_invokes_context_manager_before_turn(tmp_path):
    calls: list[int] = []

    class Spy(ContextManager):
        async def maybe_compact(self, messages):
            calls.append(len(messages))
            return messages

    engine = SessionEngine(
        provider=MockProvider([script_text("ok")]), tools=[], system="s",
        sandbox=None, model="mock", context_manager=Spy(),
    )
    _ = [ev async for ev in engine.submit("hi")]
    assert calls  # maybe_compact 在调模型前被触发


async def test_engine_without_memory_unchanged(tmp_path):
    # 不传 memory/context → 行为不变（system 原样、无副作用）
    cap = CapturingProvider(script_text("ok"))
    engine = SessionEngine(provider=cap, tools=[], system="纯净", sandbox=None, model="mock")
    _ = [ev async for ev in engine.submit("hi")]
    assert cap.systems == ["纯净"]
