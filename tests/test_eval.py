"""Eval harness + 自进化测试（离线、确定性）。

用"经验门控"假 provider：当且仅当系统提示里含某条 lesson 时，它才会修好 bug（bash sed），
否则放弃。于是可确定性地验证自进化机制：加对经验→pass@1 升→保留；没用经验→回滚。
"""
from __future__ import annotations

import json
import re

from core.eval.harness import run_taskset
from core.eval.improve import evolve, improve
from core.eval.types import Candidate, Policy, Task
from core.scenarios.coding.scenario import CodingScenario
from core.types import StreamEvent, ToolUseBlock, Usage

LESSON = "calculator 的 bug 是把加号写成了减号，用 sed 改回来"


class LessonGatedProvider:
    """系统提示含 LESSON 才解题（bash sed 修复），否则放弃。无状态（按 system+messages 判断）。"""

    name = "fake"

    def __init__(self, lesson: str):
        self.lesson = lesson

    async def stream(self, *, system, messages, tools, model, max_tokens, extra=None):
        has = self.lesson in system
        last = messages[-1]
        last_is_tool_result = last.role == "user" and any(getattr(b, "type", "") == "tool_result" for b in last.content)
        if not has:
            yield StreamEvent(type="text_delta", text="我不确定如何修复。")
            yield StreamEvent(type="message_done", usage=Usage(), stop_reason="end_turn")
            return
        if not last_is_tool_result:
            yield StreamEvent(type="tool_use", tool_use=ToolUseBlock(
                id="b1", name="bash", input={"cmd": "sed -i 's/a - b/a + b/' calculator.py"}))
            yield StreamEvent(type="message_done", usage=Usage(), stop_reason="tool_use")
        else:
            yield StreamEvent(type="text_delta", text="已修复。")
            yield StreamEvent(type="message_done", usage=Usage(), stop_reason="end_turn")

    def count_tokens(self, messages):
        return None


def _make_task(tmp_path, tid) -> Task:
    d = tmp_path / tid
    d.mkdir()
    (d / "meta.json").write_text(json.dumps({"prompt": "修复失败的测试", "test_cmd": "python3 -m pytest -q"}))
    (d / "calculator.py").write_text("def add(a, b):\n    return a - b\n")
    (d / "test_calculator.py").write_text("from calculator import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n")
    return Task(id=tid, prompt="修复失败的测试", test_cmd="python3 -m pytest -q", workspace=str(d))


async def test_run_taskset_scores_objectively(tmp_path):
    tasks = [_make_task(tmp_path, "t1"), _make_task(tmp_path, "t2")]
    tools = CodingScenario().tools()
    p = LessonGatedProvider(LESSON)
    passed = await run_taskset(tasks, provider=p, model="fake", system=f"你是编码助手。{LESSON}", tools=tools)
    assert passed.pass_rate == 1.0
    failed = await run_taskset(tasks, provider=p, model="fake", system="你是编码助手。", tools=tools)
    assert failed.pass_rate == 0.0


async def test_improve_keeps_when_better(tmp_path):
    tasks = [_make_task(tmp_path, "t1"), _make_task(tmp_path, "t2")]
    tools = CodingScenario().tools()
    base = Policy(system_prompt="你是编码助手。")  # 无 lesson → 基线失败

    async def gen(failures, bp):  # 候选：加上正确的经验
        return Candidate(Policy(bp.system_prompt, [*bp.lessons, LESSON]), f"加经验：{LESSON}")

    rec, policy = await improve(
        tasks, provider=LessonGatedProvider(LESSON), model="fake",
        base_policy=base, tools=tools, generate_candidate=gen, val_ratio=0.5,
    )
    assert rec.baseline_pass == 0.0
    assert rec.candidate_pass == 1.0
    assert rec.kept and rec.delta == 1.0
    assert LESSON in policy.render()


async def test_improve_rolls_back_when_no_gain(tmp_path):
    tasks = [_make_task(tmp_path, "t1"), _make_task(tmp_path, "t2")]
    tools = CodingScenario().tools()
    base = Policy(system_prompt="你是编码助手。")

    async def gen(failures, bp):  # 候选：没用的经验
        return Candidate(Policy(bp.system_prompt, [*bp.lessons, "多喝热水"]), "无用经验")

    rec, policy = await improve(
        tasks, provider=LessonGatedProvider(LESSON), model="fake",
        base_policy=base, tools=tools, generate_candidate=gen, val_ratio=0.5,
    )
    assert rec.candidate_pass == 0.0 and not rec.kept
    assert policy is base  # 回滚到基线


# ---------- 多轮自进化：提升曲线 ----------
class PerTaskLessonProvider:
    """task i 的 bug 是 BUGi；系统提示含 BUGi 才用 sed 改成 OK，否则放弃。"""

    name = "fake"

    async def stream(self, *, system, messages, tools, model, max_tokens, extra=None):
        text = " ".join(b.text for m in messages for b in m.content if getattr(b, "type", "") == "text")
        match = re.search(r"BUG\d", text)
        bug = match.group(0) if match else None
        has = bug is not None and bug in system  # 仅当对应经验进了系统提示才修
        last = messages[-1]
        last_tr = last.role == "user" and any(getattr(b, "type", "") == "tool_result" for b in last.content)
        if not has:
            yield StreamEvent(type="text_delta", text="不会修")
            yield StreamEvent(type="message_done", usage=Usage(), stop_reason="end_turn")
            return
        if not last_tr:
            yield StreamEvent(type="tool_use", tool_use=ToolUseBlock(
                id="b1", name="bash", input={"cmd": f"sed -i 's/{bug}/OK/' mod.py"}))
            yield StreamEvent(type="message_done", usage=Usage(), stop_reason="tool_use")
        else:
            yield StreamEvent(type="text_delta", text="ok")
            yield StreamEvent(type="message_done", usage=Usage(), stop_reason="end_turn")

    def count_tokens(self, messages):
        return None


def _make_bug_task(tmp_path, i: int) -> Task:
    d = tmp_path / f"t{i}"
    d.mkdir()
    (d / "meta.json").write_text(json.dumps({"prompt": f"修复 mod.py：把 BUG{i} 改成 OK", "test_cmd": "python3 -m pytest -q"}))
    (d / "mod.py").write_text(f'def f():\n    return "BUG{i}"\n')
    (d / "test_mod.py").write_text('from mod import f\n\n\ndef test_f():\n    assert f() == "OK"\n')
    return Task(id=f"t{i}", prompt=f"修复 mod.py：把 BUG{i} 改成 OK", test_cmd="python3 -m pytest -q", workspace=str(d))


async def test_evolve_produces_rising_curve(tmp_path):
    tasks = [_make_bug_task(tmp_path, i) for i in range(3)]
    tools = CodingScenario().tools()
    bug_of = {f"t{i}": f"BUG{i}" for i in range(3)}

    async def gen(failures, bp):  # 给第一个失败任务对应的经验
        bug = bug_of[failures[0].task_id]
        return Candidate(Policy(bp.system_prompt, [*bp.lessons, bug]), f"learn {bug}")

    res = await evolve(tasks, provider=PerTaskLessonProvider(), model="fake",
                       base_policy=Policy("你是编码助手。"), tools=tools, rounds=3, generate_candidate=gen)
    assert res.curve[0] == 0.0
    assert res.curve[-1] == 1.0
    assert res.curve == sorted(res.curve)  # 单调不降
    assert sum(1 for r in res.records if r.kept) == 3


# ---------- 隐藏测试：agent 看不到评分用例 ----------
class _SedProvider:
    name = "fake"

    def __init__(self, cmd: str):
        self.cmd = cmd

    async def stream(self, *, system, messages, tools, model, max_tokens, extra=None):
        last = messages[-1]
        last_tr = last.role == "user" and any(getattr(b, "type", "") == "tool_result" for b in last.content)
        if not last_tr:
            yield StreamEvent(type="tool_use", tool_use=ToolUseBlock(id="b1", name="bash", input={"cmd": self.cmd}))
            yield StreamEvent(type="message_done", usage=Usage(), stop_reason="tool_use")
        else:
            yield StreamEvent(type="text_delta", text="done")
            yield StreamEvent(type="message_done", usage=Usage(), stop_reason="end_turn")

    def count_tokens(self, messages):
        return None


class _NoopProvider:
    name = "fake"

    async def stream(self, *, system, messages, tools, model, max_tokens, extra=None):
        yield StreamEvent(type="text_delta", text="什么都不做")
        yield StreamEvent(type="message_done", usage=Usage(), stop_reason="end_turn")

    def count_tokens(self, messages):
        return None


def _make_hidden_task(tmp_path, name: str) -> Task:
    d = tmp_path / name
    d.mkdir()
    (d / "meta.json").write_text(json.dumps({"prompt": "让 f() 返回 2", "test_cmd": "python3 -m pytest -q"}))
    (d / "mod.py").write_text("def f():\n    return 1\n")
    hd = d / "_hidden"
    hd.mkdir()
    (hd / "test_mod.py").write_text("from mod import f\n\n\ndef test_f():\n    assert f() == 2\n")
    return Task(id=name, prompt="让 f() 返回 2", test_cmd="python3 -m pytest -q", workspace=str(d))


async def test_hidden_tests_are_scored(tmp_path):
    tools = CodingScenario().tools()
    ok = await run_taskset([_make_hidden_task(tmp_path, "fix")],
                           provider=_SedProvider("sed -i 's/return 1/return 2/' mod.py"),
                           model="fake", system="助手", tools=tools)
    assert ok.pass_rate == 1.0  # 修对 → 隐藏测试通过
    bad = await run_taskset([_make_hidden_task(tmp_path, "noop")],
                            provider=_NoopProvider(), model="fake", system="助手", tools=tools)
    assert bad.pass_rate == 0.0  # 没改 → 隐藏测试失败（证明评分用的是隐藏测试）
