# 打包成 macOS .app

Agent Y 桌面版 = **pywebview 窗口** + **内嵌 FastAPI 后端**（同一进程）+ **前端静态产物**（后端在 `/` 提供，与 API 同源，免跨域）。

## 一键打包
```bash
scripts/build_app.sh          # 构建前端 → 装依赖 → PyInstaller → dist/Agent Y.app
```
产物 `dist/Agent Y.app` 双击运行（首次启动 macOS 可能拦截：右键→打开）。

> 打包与 GUI **必须在 macOS 本机**跑，不能在容器/headless CI。

## 分步（排错时）
```bash
cd agent-y && npm install && npm run build   # 1. 前端 → agent-y/dist
pip install -e ".[desktop,office,obs]"        # 2. pywebview + pyinstaller + 办公/可观测
pyinstaller --noconfirm packaging/agenty.spec # 3. 打包
```

## 开发态直接跑（不打包）
```bash
cd agent-y && npm run build      # 出 dist（desktop 读它）
python -m desktop.main           # 起后端 + 开窗口
```

## 工作原理
- `desktop/main.py`：后台线程起 `uvicorn`（127.0.0.1:8765）→ 等 `/health` → `webview.create_window` 加载 `http://127.0.0.1:8765/`。数据落 `~/.agenty`（`AGENTY_DATA` 可改）。
- `server/app.py` `_default_frontend()`：开发读 `agent-y/dist`；打包后(`sys.frozen`)读 `sys._MEIPASS/frontend`。末尾 `app.mount("/", StaticFiles(html=True))` 在所有 API 路由之后兜底，不抢 `/sessions` 等。
- `packaging/agenty.spec`：`collect_submodules` 收齐 uvicorn/anthropic 等动态 import；`datas` 把 `agent-y/dist` 打进包内 `frontend`。

## 已知事项
- BYOK 密钥走环境变量 / OS keychain，不进包。
- 首次打包体积较大（含 Python 运行时 + 依赖）；可在 spec 的 `excludes` 里裁剪。
- 真模型需在 app 内配置 provider（或运行前设 `AGENTY_PROVIDER`/`AGENTY_BASE_URL`/`AGENTY_MODEL`/key 环境变量）。
