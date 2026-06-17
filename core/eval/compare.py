"""模型对比（PRD F4.3）。见 docs/design.md §6.2。

同一任务集跑多个模型，出通过率(pass@1) + 墙钟延迟对比，便于选性价比最高的。
v1：多模型走同一 provider（如 DeepSeek 的 chat/reasoner）；跨厂商对比后续扩。
"""
from __future__ import annotations

import time
from typing import Any

from core.eval.harness import run_taskset


async def compare_models(
    tasks: list, models: list[str], *, provider: Any, system: str, tools: list
) -> list[dict]:
    """对每个模型跑同一任务集，返回 [{model, pass_rate, n, latency_s}]（按通过率降序）。"""
    rows: list[dict] = []
    for model in models:
        t0 = time.monotonic()
        run = await run_taskset(tasks, provider=provider, model=model, system=system, tools=tools)
        rows.append({
            "model": model, "pass_rate": run.pass_rate,
            "n": len(run.results), "latency_s": round(time.monotonic() - t0, 1),
        })
    rows.sort(key=lambda r: r["pass_rate"], reverse=True)
    return rows
