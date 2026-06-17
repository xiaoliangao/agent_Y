"""Tracer 接口 → console / Langfuse。见 docs/design.md §6.1。

每个 span 记输入输出摘要 / token / 延迟 / 父子关系。M1 用 ConsoleTracer。
span 树结构 = trace 落库 schema = 未来喂自进化的 eval 样本来源。
"""
from __future__ import annotations

from typing import Any, Protocol


class SpanCtx(Protocol):
    def __enter__(self) -> "SpanCtx": ...
    def __exit__(self, *exc: Any) -> None: ...
    def set(self, **attrs: Any) -> None: ...  # 记 token/延迟/输入输出摘要


class Tracer(Protocol):
    def span(self, name: str, parent: str | None = None, **attrs: Any) -> SpanCtx: ...


class ConsoleTracer:
    """M1 最简实现：打印 run/llm/tool span。TODO(M1 Issue#9)。"""

    def span(self, name: str, parent: str | None = None, **attrs: Any) -> SpanCtx:
        raise NotImplementedError
