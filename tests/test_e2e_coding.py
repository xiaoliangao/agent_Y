"""端到端：在样例工作区里"读→跑测试(失败)→改→跑测试(通过)"，验证编码闭环（M1 验收）。

用 MockProvider 脚本驱动（离线、无需真模型），但工具/沙箱/测试都是真的在跑。
"""
from __future__ import annotations

import shutil
from pathlib import Path

from core.engine import SessionEngine
from core.harness.approval import ApprovalMode
from core.providers.mock import MockProvider, script_text, script_tool
from core.sandbox.local import LocalExecutor
from core.scenarios.coding.scenario import CodingScenario

SAMPLE = Path(__file__).resolve().parent.parent / "examples" / "fix_failing_test"


async def test_fix_failing_test_e2e(tmp_path):
    for f in ("calculator.py", "test_calculator.py"):
        shutil.copy(SAMPLE / f, tmp_path / f)

    scenario = CodingScenario()
    provider = MockProvider([
        script_tool("先看代码", "read_file", {"path": "calculator.py"}, "r1"),
        script_tool("跑测试", "bash", {"cmd": "python3 -m pytest -q"}, "b1"),
        script_tool("修 bug", "edit_file",
                    {"path": "calculator.py", "old_string": "a - b", "new_string": "a + b"}, "e1"),
        script_tool("再跑测试", "bash", {"cmd": "python3 -m pytest -q"}, "b2"),
        script_text("已把减号改成加号，测试通过。"),
    ])
    engine = SessionEngine(
        provider=provider, tools=scenario.tools(), system=scenario.system_prompt(),
        sandbox=LocalExecutor(str(tmp_path)), model="mock", approval_mode=ApprovalMode.AUTO,
    )
    events = [ev async for ev in engine.submit("修复 calculator 的失败测试")]

    assert [e.reason for e in events if e.kind == "done"] == ["completed"]
    assert "a + b" in (tmp_path / "calculator.py").read_text()

    bash_results = [
        b for e in events if e.kind == "tool_results"
        for b in e.message.content if str(b.content).startswith("exit_code=")
    ]
    assert len(bash_results) == 2
    assert bash_results[0].is_error  # 改前：测试失败
    assert bash_results[1].content.startswith("exit_code=0")  # 改后：测试通过
    assert not bash_results[1].is_error
