"""自进化：据失败生成改进候选 → 留出验证集重跑 → 仅当提升才保留，否则回滚。

见 docs/design.md §6.2 + research.md §自进化（v1=规则+LLM反思，编码测试当客观真值）。
v1 进化对象 = Policy（系统提示 + 习得经验）。候选生成可注入；默认用 LLM 反思。
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from core.eval.harness import run_taskset
from core.eval.types import Candidate, ImprovementRecord, Policy, Task, TaskResult
from core.types import Message, TextBlock

# 候选生成器签名：(failures, base_policy) -> Candidate（async）
CandidateGen = Callable[[list[TaskResult], Policy], Awaitable[Candidate]]


async def llm_reflect_candidate(
    failures: list[TaskResult], base_policy: Policy, *, provider: Any, model: str,
) -> Candidate:
    """默认候选生成：让模型据失败给一条要加进系统提示的'经验'。"""
    summary = "\n".join(f"- 任务 {r.task_id} 失败：{r.detail[:200]}" for r in failures) or "（无失败详情）"
    prompt = (
        f"下面是 agent 在编码任务上的失败：\n{summary}\n\n"
        "请给出**一条**简短、通用、可操作的经验（一句话），加进它的系统提示，帮助下次成功。只输出这一句。"
    )
    parts: list[str] = []
    async for ev in provider.stream(
        system="你是帮助改进编码 agent 的反思助手。", model=model, max_tokens=200,
        messages=[Message(role="user", content=[TextBlock(text=prompt)])], tools=[],
    ):
        if ev.type == "text_delta":
            parts.append(ev.text or "")
    lesson = "".join(parts).strip() or "先读代码与测试、定位失败根因再改，并跑测试验证后才算完成。"
    return Candidate(
        policy=Policy(base_policy.system_prompt, [*base_policy.lessons, lesson]),
        change_desc=f"加经验：{lesson[:80]}",
    )


def _split(tasks: list[Task], val_ratio: float) -> tuple[list[Task], list[Task]]:
    n = len(tasks)
    k = max(1, int(round(n * val_ratio)))
    val = tasks[:k]
    train = tasks[k:] or tasks  # 任务太少时 train 退化为全集（仍能产生失败信号）
    return train, val


async def improve(
    tasks: list[Task], *, provider: Any, model: str, base_policy: Policy, tools: list,
    generate_candidate: CandidateGen | None = None, val_ratio: float = 0.5, max_turns: int = 20,
) -> tuple[ImprovementRecord, Policy]:
    """一轮自进化。返回 (改进记录, 应采用的 policy[未提升则回滚为 base])。"""
    gen: CandidateGen = generate_candidate or (
        lambda failures, bp: llm_reflect_candidate(failures, bp, provider=provider, model=model)
    )
    train, val = _split(tasks, val_ratio)

    base_run = await run_taskset(val, provider=provider, model=model, system=base_policy.render(), tools=tools, max_turns=max_turns)
    train_run = await run_taskset(train, provider=provider, model=model, system=base_policy.render(), tools=tools, max_turns=max_turns)
    failures = [r for r in train_run.results if not r.passed]

    candidate = await gen(failures, base_policy)
    cand_run = await run_taskset(val, provider=provider, model=model, system=candidate.policy.render(), tools=tools, max_turns=max_turns)

    kept = cand_run.pass_rate > base_run.pass_rate  # 只升不降才保留，否则回滚
    record = ImprovementRecord(base_run.pass_rate, cand_run.pass_rate, kept, candidate.change_desc)
    return record, (candidate.policy if kept else base_policy)
