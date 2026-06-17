"""子 agent 工具（spawn_agent）：隔离上下文跑子任务、能用工具、回传结论。"""
from __future__ import annotations

from core.providers.mock import MockProvider, script_text, script_tool
from core.tools.subagent import SpawnAgentInput, SpawnAgentTool
from core.tools.write import WriteFileTool
from tests.helpers import make_ctx


def _noop(_chunk):
    return None


async def test_spawn_agent_returns_conclusion(tmp_path):
    provider = MockProvider([script_text("子 agent 的结论：完成了")])
    tool = SpawnAgentTool(provider=provider, model="mock", tools=[], system="你是子 agent")
    res = await tool.call(SpawnAgentInput(task="查一下 X"), make_ctx(tmp_path), _noop)
    assert "子 agent 的结论" in res.data


async def test_spawn_agent_can_use_tools(tmp_path):
    provider = MockProvider([
        script_tool("写文件", "write_file", {"path": "sub.txt", "content": "hi"}, "t1"),
        script_text("已写好 sub.txt"),
    ])
    tool = SpawnAgentTool(provider=provider, model="mock", tools=[WriteFileTool()], system="子")
    res = await tool.call(SpawnAgentInput(task="写个文件"), make_ctx(tmp_path), _noop)
    assert "已写好" in res.data
    assert (tmp_path / "sub.txt").read_text() == "hi"


async def test_spawn_agent_not_read_only():
    t = SpawnAgentTool(provider=None, model="m", tools=[], system="s")
    assert t.is_read_only(SpawnAgentInput(task="x")) is False
