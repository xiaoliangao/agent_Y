#!/usr/bin/env bash
# 把 Agent Y 打成可分发的 macOS 安装包 .dmg（拖进 Applications 即装）。
# 用法：
#   scripts/build_dmg.sh              # 先构建 .app 再打 dmg
#   scripts/build_dmg.sh --skip-build # 复用已存在的 dist/Agent Y.app
# 产物：dist/Agent-Y-<版本>.dmg
#
# 前置：macOS 本机；构建 .app 需 Node 18+ 与 Python 3.10+（见 build_app.sh）。
# 注：未做 Apple 签名/公证 —— 用户首次打开需「右键 → 打开」（README 有说明）。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

VERSION="${AGENTY_VERSION:-$(python -c "import tomllib;print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])" 2>/dev/null || echo 0.1.0)}"
APP="dist/Agent Y.app"
DMG="dist/Agent-Y-${VERSION}.dmg"

if [[ "${1:-}" != "--skip-build" ]]; then
  echo "[1/3] 构建 .app"
  bash scripts/build_app.sh
fi
[ -d "$APP" ] || { echo "✗ 找不到 $APP（先不带 --skip-build 跑一次）"; exit 1; }

echo "[2/3] 组织 dmg 内容（.app + Applications 快捷方式）"
STAGE="$(mktemp -d)/AgentY"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"

echo "[3/3] 生成 $DMG"
rm -f "$DMG"
hdiutil create -volname "Agent Y" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
rm -rf "$(dirname "$STAGE")"

SIZE="$(du -h "$DMG" | cut -f1)"
echo "✅ 安装包就绪：$DMG（$SIZE）"
echo "   分发：拖进 GitHub Release 即可；用户下载后双击 → 把 Agent Y 拖到 Applications。"
