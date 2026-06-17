"""待办 / 提醒 持久化（SQLite）。见 docs/design.md §7（todos / reminders 表）。

时间一律存 ISO-8601 UTC 字符串（`...Z`）——同格式下字典序即时间序，due 判定可直接比较。
"""
from __future__ import annotations

import datetime
import os
import sqlite3
import uuid


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SchedulerStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)) or ".", exist_ok=True)
        self._init()

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def _init(self) -> None:
        with self._conn() as c:
            c.executescript(
                """
                CREATE TABLE IF NOT EXISTS todos(
                  id TEXT PRIMARY KEY, text TEXT, done INTEGER DEFAULT 0,
                  due TEXT, created_at TEXT);
                CREATE TABLE IF NOT EXISTS reminders(
                  id TEXT PRIMARY KEY, todo_id TEXT, text TEXT, fire_at TEXT,
                  repeat TEXT, fired INTEGER DEFAULT 0, created_at TEXT);
                CREATE TABLE IF NOT EXISTS automations(
                  id TEXT PRIMARY KEY, name TEXT, schedule TEXT, prompt TEXT,
                  scenario TEXT DEFAULT 'assistant', enabled INTEGER DEFAULT 1,
                  last_run TEXT, created_at TEXT);
                CREATE TABLE IF NOT EXISTS review_queue(
                  id TEXT PRIMARY KEY, automation_id TEXT, title TEXT, output TEXT,
                  status TEXT DEFAULT 'pending', created_at TEXT);
                """
            )

    # ---------- todos ----------
    def add_todo(self, text: str, due: str | None = None) -> dict:
        tid = "todo_" + uuid.uuid4().hex[:10]
        with self._conn() as c:
            c.execute(
                "INSERT INTO todos(id,text,done,due,created_at) VALUES(?,?,0,?,?)",
                (tid, text, due, now_iso()),
            )
        return self.get_todo(tid)  # type: ignore[return-value]

    def get_todo(self, tid: str) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM todos WHERE id=?", (tid,)).fetchone()
            return _todo(r) if r else None

    def list_todos(self, include_done: bool = True) -> list[dict]:
        sql = "SELECT * FROM todos"
        if not include_done:
            sql += " WHERE done=0"
        sql += " ORDER BY COALESCE(due,''), created_at"
        with self._conn() as c:
            return [_todo(r) for r in c.execute(sql).fetchall()]

    def update_todo(
        self, tid: str, *, done: bool | None = None, text: str | None = None, due: str | None = None
    ) -> dict | None:
        sets, vals = [], []
        if done is not None:
            sets.append("done=?")
            vals.append(1 if done else 0)
        if text is not None:
            sets.append("text=?")
            vals.append(text)
        if due is not None:
            sets.append("due=?")
            vals.append(due)
        if sets:
            with self._conn() as c:
                c.execute(f"UPDATE todos SET {','.join(sets)} WHERE id=?", (*vals, tid))
        return self.get_todo(tid)

    def delete_todo(self, tid: str) -> bool:
        with self._conn() as c:
            cur = c.execute("DELETE FROM todos WHERE id=?", (tid,))
            return cur.rowcount > 0

    # ---------- reminders ----------
    def add_reminder(
        self, text: str, fire_at: str, *, todo_id: str | None = None, repeat: str | None = None
    ) -> dict:
        rid = "rem_" + uuid.uuid4().hex[:10]
        with self._conn() as c:
            c.execute(
                "INSERT INTO reminders(id,todo_id,text,fire_at,repeat,fired,created_at) "
                "VALUES(?,?,?,?,?,0,?)",
                (rid, todo_id, text, fire_at, repeat, now_iso()),
            )
        return self.get_reminder(rid)  # type: ignore[return-value]

    def get_reminder(self, rid: str) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM reminders WHERE id=?", (rid,)).fetchone()
            return _reminder(r) if r else None

    def list_reminders(self) -> list[dict]:
        with self._conn() as c:
            rs = c.execute("SELECT * FROM reminders ORDER BY fire_at").fetchall()
            return [_reminder(r) for r in rs]

    def delete_reminder(self, rid: str) -> bool:
        with self._conn() as c:
            cur = c.execute("DELETE FROM reminders WHERE id=?", (rid,))
            return cur.rowcount > 0

    def due_reminders(self, now: str) -> list[dict]:
        """未触发且到点（fire_at <= now）的提醒。"""
        with self._conn() as c:
            rs = c.execute(
                "SELECT * FROM reminders WHERE fired=0 AND fire_at<=? ORDER BY fire_at", (now,)
            ).fetchall()
            return [_reminder(r) for r in rs]

    def mark_fired(self, rid: str, *, next_fire_at: str | None = None) -> None:
        with self._conn() as c:
            if next_fire_at:  # 周期提醒：重排下次、保持未触发
                c.execute("UPDATE reminders SET fire_at=?, fired=0 WHERE id=?", (next_fire_at, rid))
            else:
                c.execute("UPDATE reminders SET fired=1 WHERE id=?", (rid,))


    # ---------- automations ----------
    def add_automation(
        self, name: str, schedule: str, prompt: str, *, scenario: str = "assistant"
    ) -> dict:
        aid = "auto_" + uuid.uuid4().hex[:10]
        with self._conn() as c:
            c.execute(
                "INSERT INTO automations(id,name,schedule,prompt,scenario,enabled,last_run,created_at)"
                " VALUES(?,?,?,?,?,1,NULL,?)",
                (aid, name, schedule, prompt, scenario, now_iso()),
            )
        return self.get_automation(aid)  # type: ignore[return-value]

    def get_automation(self, aid: str) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM automations WHERE id=?", (aid,)).fetchone()
            return _automation(r) if r else None

    def list_automations(self) -> list[dict]:
        with self._conn() as c:
            return [_automation(r) for r in c.execute("SELECT * FROM automations ORDER BY created_at").fetchall()]

    def update_automation(self, aid: str, **fields) -> dict | None:
        cols = {"name", "schedule", "prompt", "scenario", "enabled"}
        sets, vals = [], []
        for k, v in fields.items():
            if k in cols and v is not None:
                sets.append(f"{k}=?")
                vals.append(int(v) if k == "enabled" else v)
        if sets:
            with self._conn() as c:
                c.execute(f"UPDATE automations SET {','.join(sets)} WHERE id=?", (*vals, aid))
        return self.get_automation(aid)

    def delete_automation(self, aid: str) -> bool:
        with self._conn() as c:
            return c.execute("DELETE FROM automations WHERE id=?", (aid,)).rowcount > 0

    def mark_automation_run(self, aid: str, when: str | None = None) -> None:
        with self._conn() as c:
            c.execute("UPDATE automations SET last_run=? WHERE id=?", (when or now_iso(), aid))

    # ---------- review_queue ----------
    def add_review(self, automation_id: str, title: str, output: str) -> dict:
        rid = "rev_" + uuid.uuid4().hex[:10]
        with self._conn() as c:
            c.execute(
                "INSERT INTO review_queue(id,automation_id,title,output,status,created_at)"
                " VALUES(?,?,?,?,'pending',?)",
                (rid, automation_id, title, output, now_iso()),
            )
        return self.get_review(rid)  # type: ignore[return-value]

    def get_review(self, rid: str) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM review_queue WHERE id=?", (rid,)).fetchone()
            return _review(r) if r else None

    def list_reviews(self, status: str | None = None) -> list[dict]:
        sql = "SELECT * FROM review_queue"
        args: tuple = ()
        if status:
            sql += " WHERE status=?"
            args = (status,)
        sql += " ORDER BY created_at DESC"
        with self._conn() as c:
            return [_review(r) for r in c.execute(sql, args).fetchall()]

    def decide_review(self, rid: str, decision: str) -> dict | None:
        status = "accepted" if decision == "accept" else "discarded"
        with self._conn() as c:
            c.execute("UPDATE review_queue SET status=? WHERE id=?", (status, rid))
        return self.get_review(rid)


def _automation(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "name": r["name"], "schedule": r["schedule"], "prompt": r["prompt"],
            "scenario": r["scenario"], "enabled": bool(r["enabled"]), "last_run": r["last_run"],
            "created_at": r["created_at"]}


def _review(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "automation_id": r["automation_id"], "title": r["title"],
            "output": r["output"], "status": r["status"], "created_at": r["created_at"]}


def _todo(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "text": r["text"], "done": bool(r["done"]),
            "due": r["due"], "created_at": r["created_at"]}


def _reminder(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "todo_id": r["todo_id"], "text": r["text"], "fire_at": r["fire_at"],
            "repeat": r["repeat"], "fired": bool(r["fired"]), "created_at": r["created_at"]}
