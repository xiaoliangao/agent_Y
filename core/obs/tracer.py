"""Tracer 接口 → console / Langfuse / null / recording。见 docs/design.md §6.1。

span 自动嵌套：用 contextvars 记"当前 span"，子 span 自动认它作 parent（无需层层传 id）。
asyncio.gather 会为每个子任务复制 context，故并行工具 span 各自认上层为父、互不串扰。
每个 span 记 name/kind/parent/attrs/latency/error。后端只需实现 _on_start/_on_end。
"""
from __future__ import annotations

import contextvars
import itertools
import sys
import time
from typing import Any, Protocol, TextIO

_counter = itertools.count(1)
_current: contextvars.ContextVar = contextvars.ContextVar("agenty_span", default=None)


class SpanCtx(Protocol):
    def __enter__(self) -> "SpanCtx": ...
    def __exit__(self, *exc: Any) -> Any: ...
    def set(self, **attrs: Any) -> None: ...  # 记 token/延迟/输入输出摘要


class Tracer(Protocol):
    def span(self, name: str, parent: str | None = None, **attrs: Any) -> SpanCtx: ...


def summarize(v: Any, limit: int = 200) -> str:
    """把任意值压成一行短摘要（trace 只放摘要，全文进 transcript）。"""
    try:
        s = v if isinstance(v, str) else repr(v)
    except Exception:
        s = "<unrepr>"
    s = " ".join(s.split())
    return s if len(s) <= limit else s[: limit - 1] + "…"


class Span:
    """通用 span 生命周期。后端实现 BaseTracer._on_start/_on_end 即可。"""

    def __init__(self, tracer: "BaseTracer", name: str, parent: str | None, attrs: dict[str, Any]):
        self.tracer = tracer
        self.id = f"span_{next(_counter)}"
        self.name = name
        self.parent = parent if parent is not None else _current.get()
        self.kind = str(attrs.get("kind", ""))
        self.attrs = dict(attrs)
        self.depth = 0
        self.latency_ms = 0.0
        self.error: str | None = None
        self.backend: Any = None  # 后端句柄（如 langfuse span）
        self._t0 = 0.0
        self._token: Any = None

    def set(self, **attrs: Any) -> None:
        self.attrs.update(attrs)

    def __enter__(self) -> "Span":
        self._t0 = time.monotonic()
        self.depth = self.tracer._depth
        self.tracer._depth += 1
        self._token = _current.set(self.id)
        self.tracer._on_start(self)
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        self.latency_ms = (time.monotonic() - self._t0) * 1000.0
        if exc_type is not None:
            self.error = f"{exc_type.__name__}: {summarize(exc)}"
        if self._token is not None:
            _current.reset(self._token)
        self.tracer._depth = max(0, self.tracer._depth - 1)
        self.tracer._on_end(self)
        return False  # 不吞异常


class BaseTracer:
    def __init__(self) -> None:
        self._depth = 0

    def span(self, name: str, parent: str | None = None, **attrs: Any) -> Span:
        return Span(self, name, parent, attrs)

    def _on_start(self, span: Span) -> None: ...
    def _on_end(self, span: Span) -> None: ...


class NullTracer(BaseTracer):
    """什么都不做（关闭 trace 时用）。"""


class ConsoleTracer(BaseTracer):
    """把 span 以缩进树打印（run/llm/tool）。"""

    def __init__(self, out: TextIO | None = None) -> None:
        super().__init__()
        self._out = out or sys.stdout

    def _on_end(self, span: Span) -> None:
        indent = "  " * span.depth
        kind = f"[{span.kind}]" if span.kind else ""
        mark = "✗" if span.error else "▸"
        bits = [f"{span.latency_ms:.0f}ms"]
        for k in ("model", "tokens", "tools", "output", "input"):
            v = span.attrs.get(k)
            if v is not None:
                bits.append(f"{k}={summarize(v, 80)}")
        if span.error:
            bits.append(span.error)
        print(f"{indent}{mark} {span.name}{kind} ({', '.join(bits)})", file=self._out)


class RecordingTracer(BaseTracer):
    """测试用：把每个结束的 span 收进列表。"""

    def __init__(self) -> None:
        super().__init__()
        self.spans: list[Span] = []

    def _on_end(self, span: Span) -> None:
        self.spans.append(span)


def build_tracer(*, console: bool = True) -> Tracer:
    """配置齐全 → LangfuseTracer；否则 ConsoleTracer（console=True）或 NullTracer。"""
    from core.obs.langfuse import LangfuseTracer

    lf = LangfuseTracer()
    if lf.enabled:
        return lf
    return ConsoleTracer() if console else NullTracer()
