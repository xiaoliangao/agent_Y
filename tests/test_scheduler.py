"""Scheduler：待办 CRUD + 提醒到点触发 + 周期重排。"""
from __future__ import annotations

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
