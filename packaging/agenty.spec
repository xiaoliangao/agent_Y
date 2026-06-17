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

# 排除一大堆 Agent Y 不用、但碰巧装在构建环境(conda llm)里的重型库 —— 体积从 ~1.4G 砍到几百 MB。
# 这些都不是 Agent Y 的依赖(仅需 fastapi/uvicorn/anthropic/openai/pydantic/office/pywebview)。
excludes = [
    "tkinter", "pytest", "_pytest",
    # 机器学习 / 数据
    "torch", "torchvision", "torchaudio", "tensorflow", "jax", "jaxlib", "mlx",
    "transformers", "tokenizers", "safetensors", "sentencepiece", "datasets", "accelerate",
    "sklearn", "scikit_learn", "xgboost", "lightgbm", "onnxruntime",
    "pandas", "polars", "pyarrow", "scipy", "numba", "llvmlite", "sympy",
    "cv2", "av", "fitz", "pymupdf", "PIL.ImageQt",
    # 可视化 / 笔记本 / 其它大件
    "matplotlib", "IPython", "notebook", "jupyter", "jupyter_core", "zmq", "tornado",
    "sphinx", "grpc", "google", "numpy.distutils",
    # 第二轮：仍被带进来的无关大件
    "skimage", "faiss", "statsmodels", "psycopg", "psycopg2", "psycopg_binary",
    "llguidance", "patsy", "networkx", "h5py", "tables",
]

a = Analysis(
    [os.path.join(ROOT, "desktop", "main.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
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
    info_plist={
        "NSHighResolutionCapable": True,
        "LSBackgroundOnly": False,
        # 允许 WebKit 加载本地 http://127.0.0.1（否则 ATS 拦非 https → 白屏）
        "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
    },
)
