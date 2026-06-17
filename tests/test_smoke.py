"""冒烟测试：骨架能 import、核心类型可用。随 M1 扩展为真实 e2e（design §9 Issue#12）。"""
from __future__ import annotations

from core.types import Message, StreamEvent, TextBlock, ToolUseBlock


def test_types_roundtrip():
    m = Message(role="user", content=[TextBlock(text="hi")])
    assert m.content[0].text == "hi"
    assert m.model_dump()["role"] == "user"


def test_stream_event():
    ev = StreamEvent(type="text_delta", text="x")
    assert ev.type == "text_delta" and ev.text == "x"


def test_tool_use_block():
    b = ToolUseBlock(id="t1", name="bash", input={"cmd": "ls"})
    assert b.name == "bash" and b.input["cmd"] == "ls"


def test_contract_modules_import():
    # 契约模块都能 import（Protocol 定义无运行时副作用）
    import core.harness.approval  # noqa: F401
    import core.memory.store  # noqa: F401
    import core.obs.tracer  # noqa: F401
    import core.providers.base  # noqa: F401
    import core.sandbox.base  # noqa: F401
    import core.tools.base  # noqa: F401
