"""AnthropicProvider 的流翻译 + 消息转换单测（用假事件，不连真 API）。"""
from __future__ import annotations

from types import SimpleNamespace as NS

from core.providers.anthropic import _to_anthropic_messages, translate_anthropic_stream
from core.types import Message, TextBlock, ToolResultBlock, ToolUseBlock


async def _fake_events():
    yield NS(type="message_start", message=NS(usage=NS(input_tokens=10)))
    yield NS(type="content_block_start", content_block=NS(type="text"))
    yield NS(type="content_block_delta", delta=NS(type="text_delta", text="hi "))
    yield NS(type="content_block_delta", delta=NS(type="text_delta", text="there"))
    yield NS(type="content_block_stop")
    yield NS(type="content_block_start", content_block=NS(type="tool_use", id="t1", name="bash"))
    yield NS(type="content_block_delta", delta=NS(type="input_json_delta", partial_json='{"cmd":'))
    yield NS(type="content_block_delta", delta=NS(type="input_json_delta", partial_json='"ls"}'))
    yield NS(type="content_block_stop")
    yield NS(type="message_delta", delta=NS(stop_reason="tool_use"), usage=NS(output_tokens=7))
    yield NS(type="message_stop")


async def test_translate_stream():
    evs = [e async for e in translate_anthropic_stream(_fake_events())]
    assert [e.type for e in evs] == ["text_delta", "text_delta", "tool_use", "message_done"]
    tu = next(e for e in evs if e.type == "tool_use").tool_use
    assert tu.name == "bash" and tu.input == {"cmd": "ls"}  # 分片 JSON 累积后正确 parse
    done = evs[-1]
    assert done.usage.input_tokens == 10 and done.usage.output_tokens == 7
    assert done.stop_reason == "tool_use"


def test_to_anthropic_messages():
    msgs = [
        Message(role="assistant", content=[
            TextBlock(text="hi"), ToolUseBlock(id="t1", name="bash", input={"cmd": "ls"})
        ]),
        Message(role="user", content=[ToolResultBlock(tool_use_id="t1", content="ok", is_error=False)]),
    ]
    out = _to_anthropic_messages(msgs)
    assert out[0]["content"][0] == {"type": "text", "text": "hi"}
    assert out[0]["content"][1]["type"] == "tool_use" and out[0]["content"][1]["name"] == "bash"
    assert out[1]["content"][0]["type"] == "tool_result" and out[1]["content"][0]["tool_use_id"] == "t1"
