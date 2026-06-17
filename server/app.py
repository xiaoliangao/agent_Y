"""FastAPI 应用入口：REST + SSE，仅翻译 HTTP↔SessionEngine。见 docs/design.md §4.1。

跑：`uvicorn server.app:app --host 127.0.0.1 --port 8765`
"""
from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="Agent Y", version="0.1.0")


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "agent-y", "stage": "skeleton"}


# TODO(M2): 挂载 routes/（sessions / messages-SSE / approvals / providers /
#           eval / todos / reminders / automations / folders），见 design §4.1。
