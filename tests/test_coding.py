"""edit_file 工具 + 编码场景测试。"""
from __future__ import annotations

from core.providers.mock import MockProvider, script_text, script_tool
from core.scenarios.coding.scenario import CodingScenario
from core.tools.edit import EditFileTool
from core.tools.read import ReadFileTool
from tests.helpers import collect, make_ctx, user


async def test_edit_requires_prior_read(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    provider = MockProvider([
        script_tool("改", "edit_file", {"path": "a.py", "old_string": "x = 1", "new_string": "x = 2"}, "e1"),
        script_text("done"),
    ])
    events = await collect(user("改 a.py"), provider, [EditFileTool()], make_ctx(tmp_path))
    tr = next(e for e in events if e.kind == "tool_results")
    assert tr.message.content[0].is_error
    assert "先读后写" in tr.message.content[0].content
    assert (tmp_path / "a.py").read_text() == "x = 1\n"  # 未改


async def test_edit_after_read(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    provider = MockProvider([
        script_tool("读", "read_file", {"path": "a.py"}, "r1"),
        script_tool("改", "edit_file", {"path": "a.py", "old_string": "x = 1", "new_string": "x = 2"}, "e1"),
        script_text("done"),
    ])
    events = await collect(user("读再改"), provider, [ReadFileTool(), EditFileTool()], make_ctx(tmp_path))
    assert [e.reason for e in events if e.kind == "done"] == ["completed"]
    assert (tmp_path / "a.py").read_text() == "x = 2\n"


async def test_edit_old_string_not_found(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    provider = MockProvider([
        script_tool("读", "read_file", {"path": "a.py"}, "r1"),
        script_tool("改", "edit_file", {"path": "a.py", "old_string": "y = 9", "new_string": "z"}, "e1"),
        script_text("done"),
    ])
    events = await collect(user("改"), provider, [ReadFileTool(), EditFileTool()], make_ctx(tmp_path))
    edit_tr = [e for e in events if e.kind == "tool_results"][1]
    assert edit_tr.message.content[0].is_error
    assert "未在" in edit_tr.message.content[0].content


def test_coding_scenario_tools():
    sc = CodingScenario()
    names = {t.name for t in sc.tools()}
    assert names == {"read_file", "write_file", "edit_file", "bash"}
    assert "测试" in sc.system_prompt()  # 系统提示强调 verify
