"""Eval harness：跑一个/一组编码任务，用 test_cmd 客观打分（pass@1）。见 docs/design.md §6.2。

run_task：把任务工作区复制进临时沙箱 → 让 agent 跑任务 → 跑 test_cmd 评分（exit 0=通过）。
编码任务的"客观真值"=测试通过与否，这正是自进化能量化的基础（research.md §C-17）。
"""
from __future__ import annotations

import os
import shutil
import tempfile
from typing import Any

from core.engine import SessionEngine
from core.eval.types import EvalRun, Task, TaskResult
from core.harness.approval import ApprovalMode
from core.sandbox.local import LocalExecutor


async def run_task(
    task: Task, *, provider: Any, model: str, system: str, tools: list, max_turns: int = 20,
) -> TaskResult:
    ws = tempfile.mkdtemp(prefix="agenty-eval-")
    try:
        for fn in os.listdir(task.workspace):
            if fn == "meta.json":
                continue
            src = os.path.join(task.workspace, fn)
            if os.path.isfile(src):
                shutil.copy(src, os.path.join(ws, fn))
        sandbox = LocalExecutor(ws)
        engine = SessionEngine(
            provider=provider, tools=tools, system=system, sandbox=sandbox,
            model=model, approval_mode=ApprovalMode.AUTO, max_turns=max_turns,
        )
        async for _ in engine.submit(task.prompt):  # 跑到 done
            pass
        res = await sandbox.exec(["bash", "-lc", task.test_cmd], cwd=".", timeout=120)
        detail = (res.stdout + res.stderr)[-400:]
        return TaskResult(task.id, passed=res.exit_code == 0, detail=detail)
    finally:
        shutil.rmtree(ws, ignore_errors=True)


async def run_taskset(
    tasks: list[Task], *, provider: Any, model: str, system: str, tools: list, max_turns: int = 20,
) -> EvalRun:
    results: list[TaskResult] = []
    for t in tasks:
        results.append(await run_task(t, provider=provider, model=model, system=system, tools=tools, max_turns=max_turns))
    passed = sum(1 for r in results if r.passed)
    return EvalRun(pass_rate=(passed / len(results)) if results else 0.0, results=results)
