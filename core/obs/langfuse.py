"""LangfuseTracer —— 把 span 发到自托管 Langfuse。见 docs/design.md §6.1。

惰性 import langfuse；未装 SDK 或未配 key 则 enabled=False（由 build_tracer 决定退回 Console/Null）。
span 父子用 tracer 的 contextvars 自动串。所有后端调用都裹 try/except —— 观测绝不拖垮主流程。

配置（环境变量）：LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_HOST（自托管地址）。
注：Langfuse SDK 各版本 API 略有差异，这里按 v2(trace/span/end) 适配并做了容错；
未配真实 Langfuse 实例时不影响任何功能。
"""
from __future__ import annotations

import os
from typing import Any

from core.obs.tracer import BaseTracer, Span


def _build_client(public_key: str | None, secret_key: str | None, host: str | None) -> Any:
    pk = public_key or os.environ.get("LANGFUSE_PUBLIC_KEY")
    sk = secret_key or os.environ.get("LANGFUSE_SECRET_KEY")
    host = host or os.environ.get("LANGFUSE_HOST")
    if not (pk and sk):
        return None
    try:
        from langfuse import Langfuse
    except ImportError:
        return None
    try:
        return Langfuse(public_key=pk, secret_key=sk, host=host)
    except Exception:
        return None


class LangfuseTracer(BaseTracer):
    def __init__(
        self, *, client: Any = None, public_key: str | None = None,
        secret_key: str | None = None, host: str | None = None,
    ) -> None:
        super().__init__()
        self._client = client if client is not None else _build_client(public_key, secret_key, host)
        self._handles: dict[str, Any] = {}  # span.id -> langfuse 句柄

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def _on_start(self, span: Span) -> None:
        if self._client is None:
            return
        try:
            parent = self._handles.get(span.parent) if span.parent else None
            if parent is not None and hasattr(parent, "span"):
                handle = parent.span(name=span.name)  # 子 span
            else:
                handle = self._client.trace(name=span.name)  # 顶层 → 起 trace
            span.backend = handle
            self._handles[span.id] = handle
        except Exception:
            pass

    def _on_end(self, span: Span) -> None:
        if self._client is None:
            return
        handle = self._handles.pop(span.id, None)
        if handle is None:
            return
        try:
            meta = dict(span.attrs)
            meta["latency_ms"] = round(span.latency_ms, 1)
            if span.error:
                meta["error"] = span.error
            if hasattr(handle, "end"):
                handle.end(metadata=meta, level="ERROR" if span.error else "DEFAULT")
            elif hasattr(handle, "update"):
                handle.update(metadata=meta)
        except Exception:
            pass

    def flush(self) -> None:
        if self._client is not None:
            try:
                self._client.flush()
            except Exception:
                pass
