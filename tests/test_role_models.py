"""按角色配模型（PRD F1.4）：settings.model_for / server._active_model 优先级 / eval-judge 模型路由。

全离线：settings 是纯逻辑；_active_model 用 create_app；judge_model 路由把 run_taskset 打桩掉，
只剩反思那一次 provider 调用，从而断言它用的是 judge 角色模型而非任务执行模型。
"""
from __future__ import annotations

from core.eval import improve as im
from core.eval.types import EvalRun, Policy, Task, TaskResult
from core.settings import SettingsStore
from core.types import StreamEvent, Usage
from server.app import _active_model, create_app


def test_settings_model_for_and_clean(tmp_path):
    s = SettingsStore(str(tmp_path / "settings.json"))
    assert s.model_for("orchestrator") == ""  # 默认未配
    s.update(models={"orchestrator": "opus", "subagent": " ", "bogus": "x"})  # 空值/未知角色应被清掉
    assert s.model_for("orchestrator") == "opus"
    assert s.model_for("subagent") == ""
    assert "bogus" not in s.get()["models"]
    # 整体替换 + 持久化
    s2 = SettingsStore(str(tmp_path / "settings.json"))
    assert s2.model_for("orchestrator") == "opus"
    s2.update(models={"judge": "haiku"})
    assert s2.model_for("judge") == "haiku" and s2.model_for("orchestrator") == ""  # 整体替换


def test_active_model_priority(tmp_path):
    app = create_app(provider=object(), db_path=str(tmp_path / "db"), data_dir=str(tmp_path / "d"), model="base-m")
    # 无任何设置 → 兜底 app.state.model
    assert _active_model(app, "orchestrator") == "base-m"
    assert _active_model(app, "subagent") == "base-m"
    # default_model 覆盖兜底（所有未单独配的角色）
    app.state.settings.update(default_model="def-m")
    assert _active_model(app, "orchestrator") == "def-m"
    assert _active_model(app, "subagent") == "def-m"
    # 角色模型优先于 default_model，且只影响该角色
    app.state.settings.update(models={"subagent": "sub-m"})
    assert _active_model(app, "subagent") == "sub-m"
    assert _active_model(app, "orchestrator") == "def-m"


class _RecordingProvider:
    """记录每次 stream() 用的 model；任务执行被打桩跳过，只会被反思调用命中。"""

    name = "rec"

    def __init__(self):
        self.models: list[str] = []

    async def stream(self, *, system, messages, tools, model, max_tokens, extra=None):
        self.models.append(model)
        yield StreamEvent(type="text_delta", text="一条经验")
        yield StreamEvent(type="message_done", usage=Usage(), stop_reason="end_turn")

    def count_tokens(self, messages):
        return None


async def _fake_run_taskset(tasks, *, provider, model, system, tools, max_turns=20):
    return EvalRun(pass_rate=0.0, results=[TaskResult("t", passed=False, detail="boom")])  # 制造失败供反思


async def test_evolve_uses_judge_model(monkeypatch):
    monkeypatch.setattr(im, "run_taskset", _fake_run_taskset)
    prov = _RecordingProvider()
    await im.evolve([Task("t", "p", "cmd", "ws")], provider=prov, model="task-m",
                    base_policy=Policy("sys"), tools=[], rounds=1, judge_model="judge-m")
    assert prov.models == ["judge-m"]  # 反思用 judge 角色模型，不是任务执行模型


async def test_evolve_judge_defaults_to_model(monkeypatch):
    monkeypatch.setattr(im, "run_taskset", _fake_run_taskset)
    prov = _RecordingProvider()
    await im.evolve([Task("t", "p", "cmd", "ws")], provider=prov, model="task-m",
                    base_policy=Policy("sys"), tools=[], rounds=1)  # 不传 judge_model
    assert prov.models == ["task-m"]  # 默认回退到执行模型
