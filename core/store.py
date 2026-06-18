"""SQLite 持久化：会话 + 消息。见 docs/design.md §7（M2 最小版）。

单用户本地，sqlite3 足够；每次操作开一个连接（简单、无共享态）。
content_json 存整条消息的 model_dump（含 role+content），便于 Message.model_validate 还原。
"""
from __future__ import annotations

import datetime
import json
import os
import sqlite3
import uuid


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Store:
    def __init__(self, db_path: str):
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
                CREATE TABLE IF NOT EXISTS sessions(
                  id TEXT PRIMARY KEY, title TEXT, scenario TEXT,
                  status TEXT, created_at TEXT, updated_at TEXT);
                CREATE TABLE IF NOT EXISTS messages(
                  id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, seq INTEGER,
                  role TEXT, content_json TEXT, created_at TEXT);
                """
            )

    def create_session(self, title: str | None = None, scenario: str = "coding") -> dict:
        sid = "sess_" + uuid.uuid4().hex[:12]
        now = _now()
        with self._conn() as c:
            c.execute(
                "INSERT INTO sessions VALUES(?,?,?,?,?,?)",
                (sid, title or "新会话", scenario, "idle", now, now),
            )
        return self.get_session(sid)  # type: ignore[return-value]

    def get_session(self, sid: str) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
            return dict(r) if r else None

    def list_sessions(self) -> list[dict]:
        with self._conn() as c:
            rs = c.execute(
                "SELECT s.*, (SELECT COUNT(*) FROM messages m WHERE m.session_id=s.id) "
                "AS message_count FROM sessions s ORDER BY updated_at DESC"
            ).fetchall()
            return [dict(r) for r in rs]

    def delete_session(self, sid: str) -> bool:
        with self._conn() as c:
            c.execute("DELETE FROM messages WHERE session_id=?", (sid,))
            cur = c.execute("DELETE FROM sessions WHERE id=?", (sid,))
            return cur.rowcount > 0

    def rename_session(self, sid: str, title: str) -> bool:
        with self._conn() as c:
            cur = c.execute("UPDATE sessions SET title=?, updated_at=? WHERE id=?", (title, _now(), sid))
            return cur.rowcount > 0

    def set_status(self, sid: str, status: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE sessions SET status=?, updated_at=? WHERE id=?", (status, _now(), sid))

    def add_message(self, sid: str, message: dict) -> None:
        """message = Message.model_dump()（含 role + content）。"""
        with self._conn() as c:
            row = c.execute(
                "SELECT COALESCE(MAX(seq),0)+1 AS n FROM messages WHERE session_id=?", (sid,)
            ).fetchone()
            c.execute(
                "INSERT INTO messages(session_id,seq,role,content_json,created_at) VALUES(?,?,?,?,?)",
                (sid, row["n"], message.get("role"), json.dumps(message, ensure_ascii=False), _now()),
            )
            c.execute("UPDATE sessions SET updated_at=? WHERE id=?", (_now(), sid))

    def get_messages(self, sid: str) -> list[dict]:
        """返回整条消息 dict 列表（可直接 Message.model_validate）。"""
        with self._conn() as c:
            rs = c.execute(
                "SELECT content_json FROM messages WHERE session_id=? ORDER BY seq", (sid,)
            ).fetchall()
            return [json.loads(r["content_json"]) for r in rs]
