"""Eval / 自进化的数据类型。见 docs/design.md §6.2 + research.md §自进化。"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Task:
    id: str
    prompt: str          # 交给 agent 的任务描述
    test_cmd: str        # 评分命令（exit 0 = 通过）
    workspace: str       # 含该任务文件的目录（meta.json 除外会被复制进沙箱）


@dataclass
class TaskResult:
    task_id: str
    passed: bool
    detail: str = ""


@dataclass
class EvalRun:
    pass_rate: float
    results: list[TaskResult]


@dataclass
class Policy:
    """可进化的"策略"：系统提示 + 习得的经验（few-shot/lessons）。自进化就是改这个。"""
    system_prompt: str
    lessons: list[str] = field(default_factory=list)

    def render(self) -> str:
        if not self.lessons:
            return self.system_prompt
        tips = "\n".join(f"- {x}" for x in self.lessons)
        return f"{self.system_prompt}\n\n# 经验（自进化习得，务必遵守）\n{tips}"


@dataclass
class Candidate:
    policy: Policy
    change_desc: str


@dataclass
class ImprovementRecord:
    baseline_pass: float
    candidate_pass: float
    kept: bool
    change_desc: str

    @property
    def delta(self) -> float:
        return self.candidate_pass - self.baseline_pass
