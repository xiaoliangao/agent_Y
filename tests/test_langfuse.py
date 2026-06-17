"""LangfuseTracer：假 client 验证 trace/span/end 调用链 + 未配置 disabled + 错误不外溢。"""
from __future__ import annotations

from core.obs.langfuse import LangfuseTracer


class _FakeSpan:
    def __init__(self, name: str, log: list):
        self.name = name
        self.log = log

    def span(self, name: str) -> "_FakeSpan":
        self.log.append(("span", name))
        return _FakeSpan(name, self.log)

    def end(self, **_kw) -> None:
        self.log.append(("end", self.name))

    def update(self, **_kw) -> None:
        self.log.append(("update", self.name))


class _FakeClient:
    def __init__(self):
        self.log: list = []

    def trace(self, name: str) -> _FakeSpan:
        self.log.append(("trace", name))
        return _FakeSpan(name, self.log)

    def flush(self) -> None:
        self.log.append(("flush",))


def test_disabled_when_no_config(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    assert LangfuseTracer().enabled is False


def test_emits_nested_spans_to_client():
    client = _FakeClient()
    tr = LangfuseTracer(client=client)
    assert tr.enabled is True
    with tr.span("run", kind="run"):
        with tr.span("llm", kind="llm"):
            pass
    tr.flush()
    assert client.log[0] == ("trace", "run")  # 顶层起 trace
    assert ("span", "llm") in client.log  # 子 span 挂在 run 下
    assert ("end", "llm") in client.log and ("end", "run") in client.log
    assert ("flush",) in client.log


def test_backend_errors_dont_propagate():
    class Boom:
        def trace(self, name):
            raise RuntimeError("boom")

    tr = LangfuseTracer(client=Boom())
    with tr.span("run"):  # 后端抛错也不应中断主流程
        pass
