"""任务集加载。见 docs/design.md §6.2。

约定：`evals/<taskset>/<task_id>/` 下有 `meta.json`（{"prompt","test_cmd"}）+ 该任务的工作区文件。
meta.json 不会被复制进沙箱，其余文件会。
"""
from __future__ import annotations

import json
import os

from core.eval.types import Task


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
