"""Agent Y 桌面外壳：本地起 FastAPI 后端 + pywebview 窗口加载前端。见 docs/design.md §1.1。

打包成 .app：见 packaging/agenty.spec + scripts/build_app.sh。
开发运行：先 `cd agent-y && npm install && npm run build` 出 dist，再 `python -m desktop.main`。
数据（DB/记忆/会话）+ 日志默认落 ~/.agenty（可用 AGENTY_DATA 覆盖）。

排错：Finder 双击是 windowed 启动、没有控制台，所有过程都写 ~/.agenty/desktop.log。
"""
from __future__ import annotations

import logging
import os
import threading
import time
import urllib.request

HOST = "127.0.0.1"
PORT = int(os.environ.get("AGENTY_PORT", "8765"))
log = logging.getLogger("agenty.desktop")


def _data_dir() -> str:
    return os.environ.get("AGENTY_DATA") or os.path.expanduser("~/.agenty")


def _setup_logging() -> None:
    dd = _data_dir()
    os.makedirs(dd, exist_ok=True)
    logging.basicConfig(
        filename=os.path.join(dd, "desktop.log"),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def build_app():
    """构造桌面用的 FastAPI app（数据落用户目录，审批=问一下）。"""
    from core.harness.approval import ApprovalMode
    from server.app import create_app

    dd = _data_dir()
    return create_app(
        data_dir=dd, db_path=os.path.join(dd, "agenty.db"),
        approval_mode=ApprovalMode.ASK, run_scheduler=True,
    )


def serve() -> None:
    """在后台线程跑 uvicorn。用 Server 而非 uvicorn.run，并禁信号处理（非主线程不能装）。"""
    try:
        import asyncio

        import uvicorn

        config = uvicorn.Config(build_app(), host=HOST, port=PORT, log_level="warning")
        server = uvicorn.Server(config)
        server.install_signal_handlers = lambda: None  # 非主线程会抛 ValueError
        asyncio.run(server.serve())
    except Exception:
        log.exception("server thread crashed")


def wait_health(timeout: float = 60.0) -> bool:
    url = f"http://{HOST}:{PORT}/health"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.3)
    return False


def main() -> int:
    _setup_logging()
    log.info("desktop starting; port=%s data=%s", PORT, _data_dir())
    threading.Thread(target=serve, daemon=True).start()
    ready = wait_health()
    log.info("backend ready=%s", ready)  # 超时也继续开窗（总比无声退出强）
    try:
        import webview

        log.info("creating webview window")
        webview.create_window("Agent Y", f"http://{HOST}:{PORT}/", width=1200, height=820)
        webview.start()
        log.info("webview exited normally")
        return 0
    except Exception:
        log.exception("webview failed to start")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
