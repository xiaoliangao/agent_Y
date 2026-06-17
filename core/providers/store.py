"""Provider 连接管理（BYOK）。见 docs/design.md §4.1/§7、PRD F1.2/F8.1。

metadata 落 SQLite，**API key 进 OS keychain（keyring）**——key 绝不进 DB/日志/trace。
DB 只存 keychain_ref(=连接 id)。删连接即清 keychain。secrets 后端可注入（测试用内存假后端，不碰真钥匙串）。
"""
from __future__ import annotations

import datetime
import os
import sqlite3
import uuid
from typing import Protocol

_SERVICE = "agent-y"


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SecretStore(Protocol):
    def set(self, ref: str, secret: str) -> None: ...
    def get(self, ref: str) -> str | None: ...
    def delete(self, ref: str) -> None: ...


class KeyringSecrets:
    """默认实现：OS keychain（macOS Keychain via keyring）。惰性 import。"""

    def set(self, ref: str, secret: str) -> None:
        import keyring

        keyring.set_password(_SERVICE, ref, secret)

    def get(self, ref: str) -> str | None:
        import keyring

        return keyring.get_password(_SERVICE, ref)

    def delete(self, ref: str) -> None:
        import keyring

        try:
            keyring.delete_password(_SERVICE, ref)
        except Exception:
            pass


class ProviderStore:
    def __init__(self, db_path: str, *, secrets: SecretStore | None = None) -> None:
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)) or ".", exist_ok=True)
        self._secrets: SecretStore = secrets or KeyringSecrets()
        self._init()

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def _init(self) -> None:
        with self._conn() as c:
            c.execute(
                """CREATE TABLE IF NOT EXISTS provider_connections(
                     id TEXT PRIMARY KEY, provider TEXT, base_url TEXT,
                     model_default TEXT, active INTEGER DEFAULT 0, created_at TEXT)"""
            )

    def add(
        self, provider: str, api_key: str, *, base_url: str | None = None,
        model_default: str | None = None,
    ) -> dict:
        cid = "conn_" + uuid.uuid4().hex[:12]
        self._secrets.set(cid, api_key)  # key → keychain，不入库
        with self._conn() as c:
            first = c.execute("SELECT COUNT(*) AS n FROM provider_connections").fetchone()["n"] == 0
            c.execute(
                "INSERT INTO provider_connections VALUES(?,?,?,?,?,?)",
                (cid, provider, base_url, model_default, 1 if first else 0, _now()),
            )
            if first is False:
                pass  # 非首个：不自动激活
        return self.get(cid)  # type: ignore[return-value]

    def _row(self, r: sqlite3.Row) -> dict:
        return {"id": r["id"], "provider": r["provider"], "base_url": r["base_url"],
                "model_default": r["model_default"], "active": bool(r["active"]),
                "created_at": r["created_at"]}

    def get(self, cid: str) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM provider_connections WHERE id=?", (cid,)).fetchone()
            return self._row(r) if r else None

    def list(self) -> list[dict]:
        with self._conn() as c:
            rs = c.execute("SELECT * FROM provider_connections ORDER BY created_at").fetchall()
            return [self._row(r) for r in rs]  # 不含 key

    def delete(self, cid: str) -> bool:
        with self._conn() as c:
            was_active = c.execute(
                "SELECT active FROM provider_connections WHERE id=?", (cid,)
            ).fetchone()
            cur = c.execute("DELETE FROM provider_connections WHERE id=?", (cid,))
            if cur.rowcount == 0:
                return False
            if was_active and was_active["active"]:  # 删的是激活项 → 另选一个激活
                nxt = c.execute(
                    "SELECT id FROM provider_connections ORDER BY created_at LIMIT 1"
                ).fetchone()
                if nxt:
                    c.execute("UPDATE provider_connections SET active=1 WHERE id=?", (nxt["id"],))
        self._secrets.delete(cid)
        return True

    def set_active(self, cid: str) -> bool:
        with self._conn() as c:
            if not c.execute("SELECT 1 FROM provider_connections WHERE id=?", (cid,)).fetchone():
                return False
            c.execute("UPDATE provider_connections SET active=0")
            c.execute("UPDATE provider_connections SET active=1 WHERE id=?", (cid,))
        return True

    def active(self) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM provider_connections WHERE active=1 LIMIT 1").fetchone()
            return self._row(r) if r else None

    def get_key(self, cid: str) -> str | None:
        """内部用：取 key 构造 provider（绝不经 API 返回给前端）。"""
        return self._secrets.get(cid)
