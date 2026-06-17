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


class _Span:
    def __init__(self, name: str, attrs: dict[str, Any]):
        self.name = name
        self.attrs = dict(attrs)

    def __enter__(self) -> "_Span":
        return self

    def __exit__(self, *exc: Any) -> None:
        extra = " ".join(f"{k}={v}" for k, v in self.attrs.items())
        print(f"  ▸ {self.name}{(' ' + extra) if extra else ''}")

    def set(self, **attrs: Any) -> None:
        self.attrs.update(attrs)


class ConsoleTracer:
    """M1 最简实现：把每个 span 打到 stdout（run/llm/tool）。"""

    def span(self, name: str, parent: str | None = None, **attrs: Any) -> _Span:
        return _Span(name, attrs)
