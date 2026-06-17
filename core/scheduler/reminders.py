"""到点提醒触发。见 docs/design.md §4.1（reminders）/ §7。

check_due：取出已到点且未触发的提醒，逐个标记已触发（周期提醒重排下次），返回本批触发项。
上层（server/桌面）负责把它们推成系统通知 / SSE。不含调度循环本身（由调用方按节拍调用）。
"""
from __future__ import annotations

import datetime

from core.scheduler.store import SchedulerStore, now_iso


def _next_fire(fire_at: str, repeat: str) -> str | None:
    try:
        dt = datetime.datetime.strptime(fire_at, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None
    if repeat == "daily":
        dt += datetime.timedelta(days=1)
    elif repeat == "weekly":
        dt += datetime.timedelta(weeks=1)
    else:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def check_due(store: SchedulerStore, now: str | None = None) -> list[dict]:
    """返回本次到点的提醒，并把它们标记已触发（周期的重排下次）。"""
    now = now or now_iso()
    fired = store.due_reminders(now)
    for r in fired:
        nxt = _next_fire(r["fire_at"], r["repeat"]) if r.get("repeat") else None
        store.mark_fired(r["id"], next_fire_at=nxt)
    return fired
