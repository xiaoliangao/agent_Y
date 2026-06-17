"""事务类 Eval（PRD F4.4）：规则打分 / 分数解析 / LLM-judge / 综合打分 / judge 角色模型路由。

全离线：用 MockProvider（顺序吐脚本）驱动「先跑助手 agent、再调 judge」两段；
judge 路由用按 system 分流的假 provider，断言执行用 model、判分用 judge_model。
"""
from __future__ import annotations

from core.eval.assistant_eval import (
    apply_rules,
    llm_judge,
    parse_score,
    run_assistant_task,
    run_assistant_taskset,
)
from core.eval.types import AssistantTask, Rubric
from core.providers.mock import MockProvider, script_text
from core.types import StreamEvent, Usage


def test_parse_score():
    assert parse_score("点评：不错。\nSCORE: 0.8") == 0.8
    assert parse_score("SCORE：0.95") == 0.95          # 全角冒号
    assert parse_score("打 8 分。SCORE: 8") == 0.8      # 0~10 量纲归一
    assert parse_score("SCORE: 85") == 0.85            # 0~100 量纲归一
    assert parse_score("SCORE: 1.0") == 1.0
    assert parse_score("我觉得 0.7 吧") == 0.7          # 无 SCORE 行 → 取首个数字
    assert parse_score("无法评价") == 0.0


def test_apply_rules():
    out = "本周完成登录模块，修复了 3 个 bug，下周做支付。"
    rules = [
        {"type": "contains", "value": "登录"},
        {"type": "contains", "value": "支付"},
        {"type": "any", "value": ["bug", "缺陷"]},
        {"type": "min_len", "value": 10},
    ]
    score, detail = apply_rules(out, rules)
    assert score == 1.0 and len(detail) == 4
    # 部分失败
    score2, _ = apply_rules("只说了登录", rules)
    assert score2 == 0.25  # 4 条中只过 1 条（contains 登录）
    # 其余规则类型
    assert apply_rules("abc123", [{"type": "regex", "value": r"\d+"}])[0] == 1.0
    assert apply_rules("hello", [{"type": "not_contains", "value": "world"}])[0] == 1.0
    assert apply_rules("x" * 200, [{"type": "max_len", "value": 100}])[0] == 0.0
    assert apply_rules("a", [{"type": "all", "value": ["a", "b"]}])[0] == 0.0
    assert apply_rules("anything", [])[0] == 1.0          # 无规则 → 满分
    assert apply_rules("x", [{"type": "weird", "value": 1}])[0] == 0.0  # 未知类型 fail-closed


async def test_llm_judge_parses_score():
    prov = MockProvider([script_text("点评：覆盖了要点。\nSCORE: 0.9")])
    js = await llm_judge("任务", "回答内容", "要点齐全", provider=prov, model="judge")
    assert js.score == 0.9 and js.reasoning


async def test_llm_judge_empty_output_is_zero():
    prov = MockProvider([])  # 不应被调用
    js = await llm_judge("任务", "   ", "要点", provider=prov, model="judge")
    assert js.score == 0.0 and prov._i == 0  # 空输出直接判 0，不调模型


def _task() -> AssistantTask:
    return AssistantTask(
        id="weekly", prompt="起草周报",
        rubric=Rubric(criteria="覆盖三件事、简洁", rules=[
            {"type": "contains", "value": "登录"},
            {"type": "contains", "value": "支付"},
        ], pass_threshold=0.6, rule_weight=0.4),
    )


async def test_run_assistant_task_combines_rule_and_judge():
    prov = MockProvider([
        script_text("本周完成登录模块；下周做支付接入。"),  # agent 输出（两条规则都过 → 规则分 1.0）
        script_text("点评：完整。\nSCORE: 0.8"),            # judge 分 0.8
    ])
    res = await run_assistant_task(_task(), provider=prov, model="m", system="你是助手", tools=[])
    assert res.rule_score == 1.0 and res.judge_score == 0.8
    assert res.score == round(0.4 * 1.0 + 0.6 * 0.8, 3) == 0.88
    assert res.passed


async def test_run_assistant_task_fails_below_threshold():
    prov = MockProvider([
        script_text("跑题的回答"),               # 两条规则都不过 → 规则分 0
        script_text("点评：不相关。\nSCORE: 0.1"),  # judge 0.1
    ])
    res = await run_assistant_task(_task(), provider=prov, model="m", system="你是助手", tools=[])
    assert res.rule_score == 0.0 and res.judge_score == 0.1
    assert not res.passed  # 0.4*0 + 0.6*0.1 = 0.06 < 0.6


class _SystemRoutedProvider:
    """按 system 分流：评测员 system → 判分；否则当被测 agent。记录每次调用的 model。"""

    name = "routed"

    def __init__(self):
        self.models: list[str] = []

    async def stream(self, *, system, messages, tools, model, max_tokens, extra=None):
        self.models.append(model)
        text = "SCORE: 0.9" if "评测员" in system else "完成登录与支付。"
        yield StreamEvent(type="text_delta", text=text)
        yield StreamEvent(type="message_done", usage=Usage(), stop_reason="end_turn")

    def count_tokens(self, messages):
        return None


async def test_judge_model_routing():
    prov = _SystemRoutedProvider()
    res = await run_assistant_task(_task(), provider=prov, model="agent-m",
                                   judge_model="judge-m", system="你是助手", tools=[])
    assert prov.models == ["agent-m", "judge-m"]  # 执行用 model，判分用 judge_model
    assert res.judge_score == 0.9


async def test_run_assistant_taskset_aggregates():
    t = _task()
    prov = MockProvider([
        script_text("完成登录与支付。"), script_text("SCORE: 0.8"),   # 任务1 通过
        script_text("跑题"), script_text("SCORE: 0.0"),             # 任务2 不过
    ])
    run = await run_assistant_taskset([t, t], provider=prov, model="m", system="s", tools=[])
    assert len(run.results) == 2
    assert run.pass_rate == 0.5
    assert run.results[0].passed and not run.results[1].passed
