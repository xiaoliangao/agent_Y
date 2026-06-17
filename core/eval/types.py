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


# ---------- 事务类 Eval（PRD F4.4）：半客观 = 规则分 + LLM-judge 分 ----------
@dataclass
class Rubric:
    """事务类任务的评分标准。编码任务有 test_cmd 当客观真值；事务类没有，故用规则+judge。

    rules：可判定的硬约束，每条 {"type": contains|not_contains|regex|min_len|max_len|any, "value": ...}。
    rule_weight：综合分里规则分占比（0~1）；其余给 LLM-judge。无规则时退化为纯 judge。
    """
    criteria: str                                   # 给 LLM-judge 的评分要点（自然语言）
    rules: list[dict] = field(default_factory=list)
    pass_threshold: float = 0.6                     # 综合分 ≥ 此值算通过
    rule_weight: float = 0.4


@dataclass
class AssistantTask:
    id: str
    prompt: str
    rubric: Rubric
    workspace: str = ""   # 可选：含参考文件的目录（授权给助手只读）


@dataclass
class JudgeScore:
    score: float          # 0~1（LLM-judge 对照 rubric 的质量评分）
    reasoning: str = ""


@dataclass
class AssistantResult:
    task_id: str
    passed: bool
    score: float          # 综合分 = rule_weight*规则分 + (1-rule_weight)*judge 分
    rule_score: float
    judge_score: float
    detail: str = ""


@dataclass
class AssistantEvalRun:
    pass_rate: float      # 通过(score≥阈值)的任务占比
    avg_score: float      # 平均综合分
    results: list[AssistantResult]


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


@dataclass
class EvolveResult:
    curve: list[float]              # 每轮后的 pass@1（提升曲线，单调不降）
    final_policy: Policy            # 累积了所有"被保留经验"的策略
    records: list[ImprovementRecord]
