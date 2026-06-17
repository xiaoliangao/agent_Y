"""Scheduler：待办 CRUD + 提醒到点触发 + 周期重排。"""
from __future__ import annotations

from core.scheduler.automations import check_and_run, is_due
from core.scheduler.reminders import check_due
from core.scheduler.store import SchedulerStore


def test_todos_crud(tmp_path):
    s = SchedulerStore(str(tmp_path / "sched.db"))
    t = s.add_todo("买菜", due="2026-06-20T09:00:00Z")
    assert t["text"] == "买菜" and t["done"] is False
    s.update_todo(t["id"], done=True)
    assert s.get_todo(t["id"])["done"] is True
    assert s.list_todos(include_done=False) == []
    assert s.delete_todo(t["id"])
    assert s.get_todo(t["id"]) is None


def test_reminders_due_and_marked(tmp_path):
    s = SchedulerStore(str(tmp_path / "s.db"))
    s.add_reminder("过去", "2020-01-01T00:00:00Z")
    s.add_reminder("未来", "2999-01-01T00:00:00Z")
    due = check_due(s, now="2026-06-17T00:00:00Z")
    assert [r["text"] for r in due] == ["过去"]
    assert check_due(s, now="2026-06-17T00:00:00Z") == []  # 已触发不再 due


def test_reminder_repeat_reschedules(tmp_path):
    s = SchedulerStore(str(tmp_path / "s.db"))
    s.add_reminder("每日站会", "2026-06-16T08:00:00Z", repeat="daily")
    due = check_due(s, now="2026-06-17T00:00:00Z")
    assert len(due) == 1
    r = s.list_reminders()[0]
    assert r["fired"] is False and r["fire_at"] == "2026-06-17T08:00:00Z"  # 重排下一天


def test_is_due_interval():
    assert is_due("30m", None, "2026-06-17T10:00:00Z") is True
    assert is_due("30m", "2026-06-17T09:50:00Z", "2026-06-17T10:00:00Z") is False  # 才 10 分钟
    assert is_due("30m", "2026-06-17T09:20:00Z", "2026-06-17T10:00:00Z") is True   # 40 分钟


def test_is_due_daily():
    assert is_due("daily@08:00", None, "2026-06-17T07:00:00Z") is False  # 没到点
    assert is_due("daily@08:00", None, "2026-06-17T09:00:00Z") is True   # 到点没跑过
    assert is_due("daily@08:00", "2026-06-17T08:05:00Z", "2026-06-17T09:00:00Z") is False  # 今天已跑
    assert is_due("daily@08:00", "2026-06-16T08:05:00Z", "2026-06-17T09:00:00Z") is True   # 昨天跑的


def test_automations_crud(tmp_path):
    s = SchedulerStore(str(tmp_path / "s.db"))
    a = s.add_automation("每日简报", "daily@08:00", "总结今天的新闻")
    assert a["enabled"] is True and a["scenario"] == "assistant"
    s.update_automation(a["id"], enabled=False)
    assert s.get_automation(a["id"])["enabled"] is False
    assert s.delete_automation(a["id"])


async def test_check_and_run_creates_review(tmp_path):
    s = SchedulerStore(str(tmp_path / "s.db"))
    s.add_automation("brief", "30m", "do it")

    async def run_agent(prompt, scenario):
        return f"done: {prompt}"

    created = await check_and_run(s, run_agent, now="2026-06-17T10:00:00Z")
    assert len(created) == 1 and "done: do it" in created[0]["output"]
    assert await check_and_run(s, run_agent, now="2026-06-17T10:05:00Z") == []  # 30m 内不重复
    revs = s.list_reviews("pending")
    assert len(revs) == 1
    s.decide_review(revs[0]["id"], "accept")
    assert s.list_reviews("pending") == []
