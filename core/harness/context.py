"""ContextManager —— token 估算 / 工具结果清理 / 完整摘要压缩。

见 docs/design.md §5、code-study-cc.md §2（配方来自 Claude Code，纯客户端可复刻）。
三层级（阈值绝对值）：
  ① micro：清旧工具结果（便宜）—— est ≥ MICRO_TRIGGER
  ② full：调小模型 9 段式摘要（贵）—— est ≥ COMPACT_TRIGGER
  熔断：连续 3 次完整压缩失败就停（防 runaway）。
切点绝不切断 tool_use/tool_result 配对（否则 API 400）。
"""
from __future__ import annotations

import re
from typing import Any

from core.llm import complete_text
from core.types import Message, TextBlock, ToolResultBlock

_PLACEHOLDER = "[Old tool result content cleared]"
_KEEP_RECENT_TOOLRESULTS = 5
_RESERVE_OUTPUT = 20_000      # 给摘要输出预留
_COMPACT_BUFFER = 13_000
_RETAIN_MIN_TOKENS = 10_000
_RETAIN_MIN_TEXT_MSGS = 5
_RETAIN_MAX_TOKENS = 40_000
_MAX_FAILURES = 3

_SUMMARY_SYSTEM = """你在压缩一段很长的对话以节省上下文。先在 <analysis> 里逐条过对话（事后会被丢弃），
再输出 <summary>。摘要**必须覆盖**以下 9 点，简洁但不丢关键信息：
1. 用户的所有请求与意图  2. 关键技术概念  3. 涉及的文件与代码片段（带必要 snippet + 为何重要）
4. 每个错误与对应修复  5. 已解决的问题  6. **所有用户消息**（防意图漂移）
7. 待办任务  8. 当前正在做什么  9. 下一步（必须对齐用户最近的显式请求）
只输出 <analysis>…</analysis> 与 <summary>…</summary> 两段。"""


def estimate_tokens(messages: list[Message]) -> int:
    """粗估 token：text/thinking 字符数/4，tool 的 JSON /2；末尾 *4/3 保守高估（code-study §2）。"""
    total = 0
    for m in messages:
        for b in m.content:
            t = getattr(b, "type", None)
            if t == "text":
                total += len(b.text) // 4
            elif t == "thinking":
                total += len(b.thinking) // 4
            elif t == "tool_use":
                total += len(str(b.input)) // 2 + len(b.name) // 4
            elif t == "tool_result":
                total += len(str(b.content)) // 2
    return total * 4 // 3


def _strip_analysis(text: str) -> str:
    """剥掉 <analysis> scratchpad，取 <summary> 正文（缺标签则原样返回）。"""
    m = re.search(r"<summary>(.*?)</summary>", text, re.S)
    if m:
        return m.group(1).strip()
    return re.sub(r"<analysis>.*?</analysis>", "", text, flags=re.S).strip()


class ContextManager:
    def __init__(
        self,
        *,
        provider: Any = None,
        model: str = "default",
        context_window: int = 128_000,
        max_output: int = 4096,
        transcript_path: str | None = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self.window = context_window
        self.max_output = max_output
        self.transcript_path = transcript_path
        self._failures = 0

    @property
    def effective(self) -> int:
        return self.window - min(self.max_output, _RESERVE_OUTPUT)

    @property
    def compact_trigger(self) -> int:
        return self.effective - _COMPACT_BUFFER

    @property
    def micro_trigger(self) -> int:
        return int(self.effective * 0.6)

    async def maybe_compact(self, messages: list[Message]) -> list[Message]:
        """按估算 token 选层级压缩。返回新消息列表（可能原样返回）。"""
        est = estimate_tokens(messages)
        if est >= self.compact_trigger and self.provider is not None:
            if self._failures >= _MAX_FAILURES:
                return self._clear_tool_results(messages)  # 熔断后只做便宜清理
            try:
                out = await self._full_compact(messages)
                self._failures = 0
                return out
            except Exception:
                self._failures += 1
                return self._clear_tool_results(messages)
        if est >= self.micro_trigger:
            return self._clear_tool_results(messages)
        return messages

    def _clear_tool_results(self, messages: list[Message]) -> list[Message]:
        """保留最近 KEEP_RECENT 个工具结果，其余 content 换占位串（清旧、可重新获取的输出）。"""
        positions = [
            (i, j)
            for i, m in enumerate(messages)
            for j, b in enumerate(m.content)
            if getattr(b, "type", None) == "tool_result" and b.content != _PLACEHOLDER
        ]
        clear = set(positions[:-_KEEP_RECENT_TOOLRESULTS]) if len(positions) > _KEEP_RECENT_TOOLRESULTS else set()
        if not clear:
            return messages
        out: list[Message] = []
        for i, m in enumerate(messages):
            new_content = []
            for j, b in enumerate(m.content):
                if (i, j) in clear:
                    new_content.append(
                        ToolResultBlock(tool_use_id=b.tool_use_id, content=_PLACEHOLDER, is_error=b.is_error)
                    )
                else:
                    new_content.append(b)
            out.append(Message(role=m.role, content=new_content))
        return out

    async def _full_compact(self, messages: list[Message]) -> list[Message]:
        keep_from = self._retain_index(messages)
        to_summarize = messages[:keep_from]
        retained = messages[keep_from:]
        if not to_summarize:
            return messages
        summary = await complete_text(
            self.provider,
            system=_SUMMARY_SYSTEM,
            messages=[Message(role="user", content=[TextBlock(text=_render(to_summarize))])],
            model=self.model,
            max_tokens=self.max_output,
        )
        summary = _strip_analysis(summary)
        note = f"\n\n（完整记录见 transcript：{self.transcript_path}）" if self.transcript_path else ""
        head = Message(role="user", content=[TextBlock(text=f"[早前对话摘要]\n{summary}{note}")])
        return [head] + retained

    def _retain_index(self, messages: list[Message]) -> int:
        """从尾部回溯保留：≥10k token 且 ≥5 条文本消息，上限 40k；切点对齐工具配对。"""
        tok = 0
        text_msgs = 0
        idx = len(messages)
        for i in range(len(messages) - 1, -1, -1):
            mtok = estimate_tokens([messages[i]])
            if tok + mtok > _RETAIN_MAX_TOKENS and tok > 0:
                break
            tok += mtok
            if any(getattr(b, "type", None) == "text" for b in messages[i].content):
                text_msgs += 1
            idx = i
            if tok >= _RETAIN_MIN_TOKENS and text_msgs >= _RETAIN_MIN_TEXT_MSGS:
                break
        # 若保留段首是含 tool_result 的消息，往前扩一格纳入其 assistant(tool_use)，避免孤立配对
        if 0 < idx < len(messages) and any(
            getattr(b, "type", None) == "tool_result" for b in messages[idx].content
        ):
            idx -= 1
        return idx


def _render(messages: list[Message]) -> str:
    out: list[str] = []
    for m in messages:
        for b in m.content:
            t = getattr(b, "type", None)
            if t == "text":
                out.append(f"{m.role}: {b.text}")
            elif t == "thinking":
                out.append(f"{m.role}(thinking): {b.thinking}")
            elif t == "tool_use":
                out.append(f"{m.role}(tool_use {b.name}): {b.input}")
            elif t == "tool_result":
                out.append(f"{m.role}(tool_result): {str(b.content)[:500]}")
    return "\n".join(out)
