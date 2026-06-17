"""OpenAICompatProvider 的流翻译 + 消息/工具转换单测（假 chunk，不连真 API）。"""
from __future__ import annotations

from types import SimpleNamespace as NS

from core.providers.openai_compat import (
    _to_openai_messages,
    _to_openai_tools,
    translate_openai_stream,
)
from core.types import Message, TextBlock, ToolResultBlock, ToolUseBlock


def _delta(content=None, tool_calls=None):
    return NS(content=content, tool_calls=tool_calls)


def _chunk(delta=None, finish=None, usage=None):
    choices = [] if (delta is None and finish is None) else [NS(delta=delta, finish_reason=finish)]
    return NS(choices=choices, usage=usage)


def _tc(index, id=None, name=None, args=None):
    return NS(index=index, id=id, function=NS(name=name, arguments=args))


async def _fake_chunks():
    yield _chunk(_delta(content="正在"))
    yield _chunk(_delta(content="处理"))
    yield _chunk(_delta(tool_calls=[_tc(0, id="call_1", name="bash", args='{"cmd":')]))
    yield _chunk(_delta(tool_calls=[_tc(0, args='"ls"}')]))  # 分片 JSON 累积
    yield _chunk(delta=_delta(), finish="tool_calls")
    yield _chunk(usage=NS(prompt_tokens=12, completion_tokens=8))  # 末尾 usage chunk


async def test_translate_openai_stream():
    evs = [e async for e in translate_openai_stream(_fake_chunks())]
    assert [e.type for e in evs[:2]] == ["text_delta", "text_delta"]
    tu = next(e for e in evs if e.type == "tool_use").tool_use
    assert tu.name == "bash" and tu.input == {"cmd": "ls"} and tu.id == "call_1"
    done = evs[-1]
    assert done.type == "message_done"
    assert done.usage.input_tokens == 12 and done.usage.output_tokens == 8


def test_to_openai_messages_splits_tool_results():
    msgs = [
        Message(role="user", content=[TextBlock(text="hi")]),
        Message(role="assistant", content=[
            TextBlock(text="ok"), ToolUseBlock(id="c1", name="bash", input={"cmd": "ls"})
        ]),
        Message(role="user", content=[ToolResultBlock(tool_use_id="c1", content="out", is_error=False)]),
    ]
    out = _to_openai_messages("SYS", msgs)
    assert out[0] == {"role": "system", "content": "SYS"}
    assert out[1] == {"role": "user", "content": "hi"}
    assert out[2]["role"] == "assistant" and out[2]["tool_calls"][0]["function"]["name"] == "bash"
    assert out[3] == {"role": "tool", "tool_call_id": "c1", "content": "out"}


def test_to_openai_tools():
    out = _to_openai_tools([{"name": "bash", "description": "run", "input_schema": {"type": "object"}}])
    assert out[0]["type"] == "function"
    assert out[0]["function"]["name"] == "bash"
    assert out[0]["function"]["parameters"] == {"type": "object"}
