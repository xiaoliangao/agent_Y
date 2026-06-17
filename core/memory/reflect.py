"""记忆自动沉淀（反思）。见 docs/design.md §4.5、code-study-cc.md §6。

每轮结束后，让小模型从最近对话提炼"值得跨会话长期记住"的事实，按四类 taxonomy 写记忆。
v1 用**单轮受限 LLM 调用**（非完整 fork 子 agent）：只看最近 N 条、结构化输出、**写入前强制查重**。
"""
from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from core.llm import complete_text
from core.memory.store import Memory
from core.types import Message, TextBlock

if TYPE_CHECKING:
    from core.memory.store import FileMemoryStore

_TYPES = ("user", "feedback", "project", "reference")

_REFLECT_SYSTEM = """你从最近对话里提炼**值得跨会话长期记住**的事实，写成记忆。四类(闭集)：
- user: 用户角色/目标/偏好
- feedback: 用户对"你该怎么工作"的指导(含 Why)
- project: 进行中工作/决策的"为什么"(相对日期转绝对)
- reference: 外部系统/资源指针

只记**无法从代码/git/文件状态当场查到**的东西；代码结构、文件路径、架构、调试 fix recipe 一律不记(会过时变误导)。
已有记忆(避免重复)：
{existing}

输出 JSON 数组，每项 {{"name": "kebab-case-slug", "description": "一句话", "type": "四类之一", "body": "正文"}}。
没有值得记的就输出 []。不要任何解释。"""


def _slug(s: str) -> str:
    s = re.sub(r"[^\w\s-]", "", s.lower()).strip()
    return re.sub(r"[\s_]+", "-", s)[:60]


def _recent_text(messages: list[Message], n: int = 12) -> str:
    out: list[str] = []
    for m in messages[-n:]:
        for b in m.content:
            t = getattr(b, "type", None)
            if t == "text":
                out.append(f"{m.role}: {b.text}")
            elif t == "tool_use":
                out.append(f"{m.role}(tool_use {b.name}): {b.input}")
            elif t == "tool_result":
                out.append(f"{m.role}(tool_result): {str(b.content)[:200]}")
    return "\n".join(out)


def _parse_items(raw: str) -> list[dict]:
    m = re.search(r"\[.*\]", raw, re.S)
    if not m:
        return []
    try:
        arr = json.loads(m.group(0))
    except Exception:
        return []
    return [x for x in arr if isinstance(x, dict)]


async def extract_memories(
    store: "FileMemoryStore",
    provider: Any,
    model: str,
    messages: list[Message],
    *,
    max_new: int = 3,
) -> list[Memory]:
    """从最近对话提炼并写入新记忆（查重后），返回实际写入的记忆列表。"""
    convo = _recent_text(messages)
    if not convo.strip():
        return []
    existing_index = store.load_index() or "(无)"
    raw = await complete_text(
        provider,
        system=_REFLECT_SYSTEM.format(existing=existing_index),
        messages=[Message(role="user", content=[TextBlock(text=convo)])],
        model=model,
        max_tokens=800,
    )
    existing_names = {m.name for m in store._scan()}
    written: list[Memory] = []
    for item in _parse_items(raw)[:max_new]:
        name = _slug(str(item.get("name", "")))
        mtype = item.get("type", "reference")
        if not name or mtype not in _TYPES or name in existing_names:
            continue  # 空名/非法类型/重名 → 跳过（强制查重）
        mem = Memory(
            name=name,
            description=str(item.get("description", ""))[:200],
            type=mtype,
            body=str(item.get("body", "")).strip(),
        )
        await store.write(mem)
        existing_names.add(name)
        written.append(mem)
    return written
