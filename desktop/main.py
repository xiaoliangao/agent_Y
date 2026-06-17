"""Agent Y 桌面外壳：本地起 FastAPI 后端 + pywebview 窗口加载前端。见 docs/design.md §1.1。

打包成 .app：见 packaging/agenty.spec + scripts/build_app.sh。
开发运行：先 `cd agent-y && npm install && npm run build` 出 dist，再 `python -m desktop.main`。
数据（DB/记忆/会话）默认落 ~/.agenty（可用 AGENTY_DATA 覆盖）。
"""
from __future__ import annotations

import os
import threading
import time
import urllib.request

HOST = "127.0.0.1"
PORT = int(os.environ.get("AGENTY_PORT", "8765"))


def _data_dir() -> str:
    return os.environ.get("AGENTY_DATA") or os.path.expanduser("~/.agenty")


def build_app():
    """构造桌面用的 FastAPI app（数据落用户目录，审批=问一下）。"""
    from core.harness.approval import ApprovalMode
    from server.app import create_app

    dd = _data_dir()
    return create_app(
        data_dir=dd, db_path=os.path.join(dd, "agenty.db"), approval_mode=ApprovalMode.ASK
    )


def serve() -> None:
    import uvicorn

    uvicorn.run(build_app(), host=HOST, port=PORT, log_level="warning")


def wait_health(timeout: float = 20.0) -> bool:
    url = f"http://{HOST}:{PORT}/health"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.2)
    return False


def main() -> int:
    threading.Thread(target=serve, daemon=True).start()
    if not wait_health():
        print("后端启动超时", flush=True)
        return 1
    import webview

    webview.create_window("Agent Y", f"http://{HOST}:{PORT}/", width=1200, height=820)
    webview.start()  # 阻塞直到窗口关闭；后端线程是 daemon，随主进程退出
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
