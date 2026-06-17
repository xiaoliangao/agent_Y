"""事务类 Eval（PRD F4.4）：半客观打分 = 规则检查 + LLM-judge。

编码任务有 test_cmd 当客观真值（pass@1）；事务类（起草/问答/整理）没有 exit code，
故综合两路打分：
  - 规则分：可判定的硬约束（含某词、正则、长度…），确定性、便宜、防 judge 漂移。
  - judge 分：让评测模型对照 rubric 给 0~1 的质量分（语义层面）。
综合分 = rule_weight*规则分 + (1-rule_weight)*judge 分；≥ 阈值算通过。
判分模型走 F1.4 的 eval-judge 角色（judge_model），与被测模型可不同。
"""
from __future__ import annotations

import re
import shutil
import tempfile
from typing import Any

from core.engine import SessionEngine
from core.eval.types import (
    AssistantEvalRun,
    AssistantResult,
    AssistantTask,
    JudgeScore,
)
from core.harness.approval import ApprovalMode
from core.obs.tracer import build_tracer
from core.sandbox.local import LocalExecutor

_SCORE_RE = re.compile(r"SCORE\s*[:：]\s*(-?\d+(?:\.\d+)?)", re.IGNORECASE)
_FLOAT_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _clamp01(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def parse_score(raw: str) -> float:
    """从 judge 输出里抽 0~1 分：优先 `SCORE: x` 行，否则取第一个数字；都没有当 0。"""
    m = _SCORE_RE.search(raw)
    if not m:
        m = _FLOAT_RE.search(raw)
    if not m:
        return 0.0
    val = float(m.group(1) if m.re is _SCORE_RE else m.group(0))
    if val > 1:  # 容错：模型给了 0~100 / 0~10 量纲
        val = val / 100 if val > 10 else val / 10
    return _clamp01(val)


def _check_rule(rule: dict, output: str, low: str) -> bool:
    t = (rule.get("type") or "").lower()
    v = rule.get("value")
    if t == "contains":
        return str(v).lower() in low
    if t == "not_contains":
        return str(v).lower() not in low
    if t == "regex":
        return re.search(str(v), output) is not None
    if t == "min_len":
        return len(output) >= int(v)
    if t == "max_len":
        return len(output) <= int(v)
    if t == "any":  # value 为列表，命中任一即可
        return any(str(x).lower() in low for x in (v or []))
    if t == "all":  # value 为列表，需全部命中
        return all(str(x).lower() in low for x in (v or []))
    return False  # 未知规则类型：fail-closed


def apply_rules(output: str, rules: list[dict]) -> tuple[float, list[str]]:
    """逐条判定，返回 (通过比例, 每条明细)。无规则视为满分（交给 judge）。"""
    if not rules:
        return 1.0, []
    low = output.lower()
    passed = 0
    detail: list[str] = []
    for r in rules:
        ok = _check_rule(r, output, low)
        passed += int(ok)
        detail.append(f"{'✓' if ok else '✗'} {r.get('type')}:{r.get('value')}")
    return passed / len(rules), detail


async def llm_judge(prompt: str, output: str, criteria: str, *, provider: Any, model: str) -> JudgeScore:
    """让评测模型对照 criteria 给 0~1 分（最后一行 `SCORE: x`），空输出直接 0。"""
    if not output.strip():
        return JudgeScore(0.0, "空输出")
    judge_prompt = (
        "你是严格、公正的评测员。根据评分标准给被测回答打分。\n\n"
        f"# 任务\n{prompt}\n\n# 评分标准\n{criteria}\n\n"
        f'# 被测回答\n"""\n{output}\n"""\n\n'
        "先用一句话点评，再在**最后单独一行**输出 `SCORE: x`（x 为 0 到 1 的小数，1=完全满足标准）。"
    )
    from core.types import Message, TextBlock

    parts: list[str] = []
    async for ev in provider.stream(
        system="你是严格、公正的评测员，只按标准打分。", model=model, max_tokens=400,
        messages=[Message(role="user", content=[TextBlock(text=judge_prompt)])], tools=[],
    ):
        if ev.type == "text_delta":
            parts.append(ev.text or "")
    raw = "".join(parts).strip()
    return JudgeScore(parse_score(raw), raw[:300])


async def _run_agent(task: AssistantTask, *, provider, model, system, tools, max_turns) -> str:
    """跑助手 agent，收集其全部助手文本作为待评输出。"""
    ws = tempfile.mkdtemp(prefix="agenty-aeval-")
    try:
        engine = SessionEngine(
            provider=provider, tools=tools, system=system, sandbox=LocalExecutor(ws),
            model=model, approval_mode=ApprovalMode.AUTO, max_turns=max_turns,
            tracer=build_tracer(console=False),
        )
        parts: list[str] = []
        async for ev in engine.submit(task.prompt):
            if ev.kind == "text_delta" and ev.text:
                parts.append(ev.text)
        return "".join(parts).strip()
    finally:
        shutil.rmtree(ws, ignore_errors=True)


async def run_assistant_task(
    task: AssistantTask, *, provider: Any, model: str, system: str, tools: list,
    judge_model: str | None = None, max_turns: int = 12,
) -> AssistantResult:
    """跑一个事务类任务并半客观打分。judge_model 默认与 model 相同（F1.4 eval-judge 角色）。"""
    output = await _run_agent(task, provider=provider, model=model, system=system, tools=tools, max_turns=max_turns)
    rub = task.rubric
    rule_score, rule_detail = apply_rules(output, rub.rules)
    judge = await llm_judge(task.prompt, output, rub.criteria, provider=provider, model=judge_model or model)
    w = rub.rule_weight if rub.rules else 0.0  # 无规则 → 纯 judge
    score = w * rule_score + (1 - w) * judge.score
    detail = f"规则[{', '.join(rule_detail) or '无'}] judge={judge.score:.2f}({judge.reasoning[:120]})"
    return AssistantResult(
        task_id=task.id, passed=score >= rub.pass_threshold, score=round(score, 3),
        rule_score=round(rule_score, 3), judge_score=round(judge.score, 3), detail=detail,
    )


async def run_assistant_taskset(
    tasks: list[AssistantTask], *, provider: Any, model: str, system: str, tools: list,
    judge_model: str | None = None, max_turns: int = 12,
) -> AssistantEvalRun:
    results: list[AssistantResult] = []
    for t in tasks:
        results.append(await run_assistant_task(
            t, provider=provider, model=model, system=system, tools=tools,
            judge_model=judge_model, max_turns=max_turns,
        ))
    n = len(results)
    pass_rate = sum(1 for r in results if r.passed) / n if n else 0.0
    avg = sum(r.score for r in results) / n if n else 0.0
    return AssistantEvalRun(pass_rate=pass_rate, avg_score=round(avg, 3), results=results)
