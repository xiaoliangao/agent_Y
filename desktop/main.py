"""Agent Y 桌面外壳：本地起 FastAPI 后端 + pywebview 窗口加载前端。见 docs/design.md §1.1。

两种进程模式（让「关窗→收进菜单栏、后端续跑、点图标重开窗、关窗省内存」成立）：
- **host**（默认，.app 启动的就是它）：后台跑后端 + macOS 菜单栏图标(rumps)，并 spawn 一个独立的
  **窗口子进程**。关掉窗口只是杀掉子进程 → WebKit 内存被释放，后端在 host 里继续跑（定时/提醒不断）；
  点菜单栏「打开」再 spawn 一扇新窗。
- **window**（环境变量 AGENTY_MODE=window）：不起后端，只开一个 pywebview 窗口连已就绪的后端；
  关窗即本进程退出。

rumps 不可用时优雅回退到「单进程单窗、关窗即退」的旧行为。

打包成 .app：见 packaging/agenty.spec + scripts/build_app.sh。
数据（DB/记忆/会话）+ 日志默认落 ~/.agenty（可用 AGENTY_DATA 覆盖）；所有过程写 ~/.agenty/desktop.log。
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
import urllib.request

HOST = "127.0.0.1"
PORT = int(os.environ.get("AGENTY_PORT", "8765"))
URL = f"http://{HOST}:{PORT}/"
log = logging.getLogger("agenty.desktop")


def _data_dir() -> str:
    return os.environ.get("AGENTY_DATA") or os.path.expanduser("~/.agenty")


def _mode() -> str:
    """host（菜单栏+后端+窗口子进程）| window（只开窗连已有后端）。"""
    return os.environ.get("AGENTY_MODE", "host")


def _window_argv() -> list[str]:
    """spawn 一个「窗口模式」子进程的命令行：frozen 时重跑 bundle 二进制，dev 时跑模块。"""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, "-m", "desktop.main"]


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


def _no_proxy_for_loopback() -> None:
    """把回环加进 no_proxy。用户常把 HTTP_PROXY 指向本地 clash/mihomo（如 127.0.0.1:7897），
    否则连自家后端 127.0.0.1:8765 也会被代理掉 → 健康检查/自连失败。子进程继承本设置。"""
    for k in ("no_proxy", "NO_PROXY"):
        cur = os.environ.get(k, "")
        if "127.0.0.1" not in cur:
            os.environ[k] = (cur + ",127.0.0.1,localhost,::1").lstrip(",")


def wait_health(timeout: float = 60.0) -> bool:
    url = f"http://{HOST}:{PORT}/health"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 回环不走代理
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with opener.open(url, timeout=1) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.3)
    return False


class WindowApi:
    """暴露给前端的原生桥（window.pywebview.api.*）：目前只有原生「选择文件夹」。"""

    def pick_folder(self) -> str:
        try:
            import webview

            win = webview.windows[0] if webview.windows else None
            res = (win or webview).create_file_dialog(webview.FOLDER_DIALOG)
        except Exception:
            log.exception("pick_folder failed")
            return ""
        if not res:
            return ""
        return res[0] if isinstance(res, (list, tuple)) else str(res)


def _open_window_blocking() -> int:
    """在当前进程开一个 pywebview 窗口并阻塞到关闭（带原生文件夹选择桥）。"""
    try:
        import webview

        log.info("creating webview window -> %s", URL)
        webview.create_window("Agent Y", URL, width=1200, height=820, js_api=WindowApi())
        webview.start()
        log.info("webview exited normally")
        return 0
    except Exception:
        log.exception("webview failed to start")
        return 1


def run_window() -> int:
    """窗口模式：后端已在 host 进程里，等它就绪后只开窗。"""
    log.info("window mode; waiting backend")
    wait_health()
    return _open_window_blocking()


def run_host() -> int:
    """host 模式：后台后端 + 菜单栏图标 + 窗口子进程。rumps 不可用则回退单窗。"""
    threading.Thread(target=serve, daemon=True).start()
    ready = wait_health()
    log.info("backend ready=%s", ready)

    try:
        import rumps
    except Exception:
        log.warning("rumps 不可用，回退到单窗模式（关窗即退）")
        return _open_window_blocking()

    procs: dict[str, subprocess.Popen] = {}

    def open_window(_=None) -> None:
        p = procs.get("win")
        if p is not None and p.poll() is None:
            return  # 已有窗口活着，避免开重复窗
        log.info("spawning window subprocess")
        procs["win"] = subprocess.Popen(_window_argv(), env={**os.environ, "AGENTY_MODE": "window"})

    def quit_app(_=None) -> None:
        p = procs.get("win")
        if p is not None and p.poll() is None:
            p.terminate()
        rumps.quit_application()

    try:
        _set_accessory_policy()  # 菜单栏代理：尽量不在 Dock 占图标
        open_window()  # 启动即开一扇窗
        app = rumps.App("Agent Y", title="Y", quit_button=None)
        app.menu = [
            rumps.MenuItem("打开 Agent Y", callback=open_window),
            rumps.MenuItem("● 在线"),
            None,
            rumps.MenuItem("退出 Agent Y", callback=quit_app),
        ]
        app.run()
        return 0
    except Exception:
        log.exception("tray failed; falling back to single window")
        return _open_window_blocking()


def _set_accessory_policy() -> None:
    """把 host 进程设为「菜单栏代理」(不占 Dock)。失败无所谓（仅影响是否显示 Dock 图标）。"""
    try:
        from AppKit import NSApplication, NSApplicationActivationPolicyAccessory

        NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    except Exception:
        pass


def main() -> int:
    _setup_logging()
    _no_proxy_for_loopback()
    mode = _mode()
    log.info("desktop starting; mode=%s port=%s data=%s", mode, PORT, _data_dir())
    return run_window() if mode == "window" else run_host()


if __name__ == "__main__":
    raise SystemExit(main())
