"""模型对比：对每个模型跑同一任务集，按通过率降序（用 monkeypatch 绕开 eval 沙箱）。"""
from __future__ import annotations

from core.eval import compare as cmp
from core.eval.types import EvalRun, TaskResult


async def test_compare_models_sorts_by_pass_rate(monkeypatch):
    async def fake_run_taskset(tasks, provider, model, system, tools):
        rate = 1.0 if model == "good" else 0.5
        return EvalRun(pass_rate=rate, results=[TaskResult(task_id="t", passed=rate == 1.0)])

    monkeypatch.setattr(cmp, "run_taskset", fake_run_taskset)
    rows = await cmp.compare_models([{}], ["bad", "good"], provider=None, system="", tools=[])
    assert [r["model"] for r in rows] == ["good", "bad"]  # 通过率降序
    assert rows[0]["pass_rate"] == 1.0 and rows[0]["n"] == 1 and "latency_s" in rows[0]
