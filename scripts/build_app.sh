#!/usr/bin/env bash
# 把 Agent Y 打包成 macOS .app：构建前端 → 装打包依赖 → PyInstaller。
# 用法：scripts/build_app.sh   产物 → dist/Agent Y.app（双击运行）
#
# 前置：Node 18+（构建前端）、Python 3.10+。打包/GUI 必须在 macOS 本机跑（不能在容器/CI headless）。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "[1/3] 构建前端 (agent-y → dist)"
( cd agent-y && npm install && npm run build )

echo "[2/3] 安装打包依赖 (.[desktop,office])"
python -m pip install -e ".[desktop,office]"  # obs(langfuse) 可选，发布版默认不带以瘦身

echo "[3/3] PyInstaller 打包"
pyinstaller --noconfirm packaging/agenty.spec

echo "✅ 完成 → dist/Agent Y.app（双击运行；首次启动 macOS 可能拦截，右键→打开）"
