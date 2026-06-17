"""定时自动化 → review 队列。见 docs/design.md §4.1（automations/review-queue）、PRD F6.6。

到点的自动化跑一次 agent（按其 prompt+scenario），产出进 review_queue 等用户收口。
schedule 支持：`daily@HH:MM`（每天某点）/ `Nm`（每 N 分钟）/ `Nh`（每 N 小时）。
"""
from __future__ import annotations

import datetime
import re
from typing import Awaitable, Callable

from core.scheduler.store import SchedulerStore, now_iso

_FMT = "%Y-%m-%dT%H:%M:%SZ"


def _parse(iso: str) -> datetime.datetime:
    return datetime.datetime.strptime(iso, _FMT)


def is_due(schedule: str, last_run: str | None, now: str) -> bool:
    """据 schedule + 上次运行时间判断现在是否该跑。"""
    nowdt = _parse(now)
    s = schedule.strip()

    interval = re.fullmatch(r"(\d+)([mh])", s)
    if interval:
        n, unit = int(interval.group(1)), interval.group(2)
        delta = datetime.timedelta(minutes=n) if unit == "m" else datetime.timedelta(hours=n)
        return last_run is None or (nowdt - _parse(last_run)) >= delta

    daily = re.fullmatch(r"daily@(\d{1,2}):(\d{2})", s)
    if daily:
        hh, mm = int(daily.group(1)), int(daily.group(2))
        at = nowdt.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if nowdt < at:
            return False  # 今天还没到点
        return last_run is None or _parse(last_run) < at  # 今天这个点后还没跑过

    return False


async def check_and_run(
    store: SchedulerStore,
    run_agent: Callable[[str, str], Awaitable[str]],
    now: str | None = None,
) -> list[dict]:
    """跑所有到点的启用自动化，产出进 review 队列。run_agent(prompt, scenario)->输出文本。返回新建的待审项。"""
    now = now or now_iso()
    created: list[dict] = []
    for a in store.list_automations():
        if not a["enabled"] or not is_due(a["schedule"], a["last_run"], now):
            continue
        try:
            output = await run_agent(a["prompt"], a["scenario"])
        except Exception as e:  # noqa: BLE001 —— 单个自动化失败不影响其它
            output = f"[自动化执行失败] {type(e).__name__}: {e}"
        store.mark_automation_run(a["id"], now)
        created.append(store.add_review(a["id"], a["name"], output))
    return created
