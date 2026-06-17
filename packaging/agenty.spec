# PyInstaller 配置：把 Agent Y 打包成 macOS .app（pywebview 窗口 + 内嵌 FastAPI 后端 + 前端）。
# 用法：cd <repo> && pyinstaller --noconfirm packaging/agenty.spec  → dist/Agent Y.app
# 注：Analysis/PYZ/EXE/COLLECT/BUNDLE 由 PyInstaller 注入为全局名。
import os

from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.getcwd())

# uvicorn/anthropic 等有大量动态 import，显式收齐子模块，避免运行时 ModuleNotFound
hiddenimports = []
for pkg in (
    "uvicorn", "anthropic", "openai", "fastapi", "starlette",
    "pydantic", "openpyxl", "docx", "pptx", "webview",
):
    hiddenimports += collect_submodules(pkg)

# 前端构建产物 → 包内 "frontend"（server._default_frontend 在 frozen 时读 sys._MEIPASS/frontend）
datas = [(os.path.join(ROOT, "agent-y", "dist"), "frontend")]

a = Analysis(
    [os.path.join(ROOT, "desktop", "main.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest", "matplotlib"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="AgentY", console=False)
coll = COLLECT(exe, a.binaries, a.datas, name="AgentY")
app = BUNDLE(
    coll,
    name="Agent Y.app",
    icon=None,
    bundle_identifier="com.agenty.app",
    info_plist={"NSHighResolutionCapable": True, "LSBackgroundOnly": False},
)
