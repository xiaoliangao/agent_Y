"""任务集加载。见 docs/design.md §6.2。

约定：`evals/<taskset>/<task_id>/` 下有 `meta.json`（{"prompt","test_cmd"}）+ 该任务的工作区文件。
meta.json 不会被复制进沙箱，其余文件会。
"""
from __future__ import annotations

import json
import os

from core.eval.types import AssistantTask, Rubric, Task


def load_taskset(root: str) -> list[Task]:
    tasks: list[Task] = []
    if not os.path.isdir(root):
        return tasks
    for name in sorted(os.listdir(root)):
        tdir = os.path.join(root, name)
        meta_path = os.path.join(tdir, "meta.json")
        if not os.path.isfile(meta_path):
            continue
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        tasks.append(Task(id=name, prompt=meta["prompt"], test_cmd=meta["test_cmd"], workspace=tdir))
    return tasks


def load_assistant_taskset(root: str) -> list[AssistantTask]:
    """事务类任务集（PRD F4.4）。meta.json: {prompt, criteria, rules?, pass_threshold?, rule_weight?}。"""
    tasks: list[AssistantTask] = []
    if not os.path.isdir(root):
        return tasks
    for name in sorted(os.listdir(root)):
        tdir = os.path.join(root, name)
        meta_path = os.path.join(tdir, "meta.json")
        if not os.path.isfile(meta_path):
            continue
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        rub = Rubric(
            criteria=meta.get("criteria", ""),
            rules=meta.get("rules", []),
            pass_threshold=float(meta.get("pass_threshold", 0.6)),
            rule_weight=float(meta.get("rule_weight", 0.4)),
        )
        tasks.append(AssistantTask(id=name, prompt=meta["prompt"], rubric=rub, workspace=tdir))
    return tasks
