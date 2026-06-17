#!/usr/bin/env bash
# 建/拆到远程 Docker daemon 的 SSH 隧道，供 DockerSandbox 真机测试用。
# 连接信息全部从环境变量读取，**不硬编码任何服务器/密钥**（repo 可能公开）。
#
# 必填:  AGENTY_DOCKER_SSH   远程 SSH 目标，如 user@host
# 可选:  AGENTY_DOCKER_KEY   私钥路径（默认走 ssh-agent / ~/.ssh 默认 key）
#        AGENTY_DOCKER_PORT  本地转发端口（默认 23750）
#
# 用法:
#   AGENTY_DOCKER_SSH=ubuntu@1.2.3.4 AGENTY_DOCKER_KEY=~/k.key scripts/docker-tunnel.sh up
#   eval "$(scripts/docker-tunnel.sh env)"   # 导出 DOCKER_HOST / NO_PROXY
#   pytest tests/test_docker_sandbox.py
#   scripts/docker-tunnel.sh down
set -euo pipefail

PORT="${AGENTY_DOCKER_PORT:-23750}"
FWD="127.0.0.1:${PORT}:/var/run/docker.sock"
KEY_OPT=()
[ -n "${AGENTY_DOCKER_KEY:-}" ] && KEY_OPT=(-i "$AGENTY_DOCKER_KEY")

case "${1:-up}" in
  up)
    : "${AGENTY_DOCKER_SSH:?需设 AGENTY_DOCKER_SSH=user@host}"
    pkill -f "$FWD" 2>/dev/null || true
    sleep 0.3
    ssh "${KEY_OPT[@]}" -fN -o ExitOnForwardFailure=yes -o StrictHostKeyChecking=accept-new \
        -L "$FWD" "$AGENTY_DOCKER_SSH"
    echo "tunnel up → tcp://127.0.0.1:${PORT}" >&2
    echo "next: eval \"\$($0 env)\"" >&2
    ;;
  down)
    pkill -f "$FWD" && echo "tunnel down" >&2 || echo "no tunnel" >&2
    ;;
  env)
    # NO_PROXY：本机若有 HTTP 代理，docker SDK 的 requests 会把回环也走代理 → 502
    echo "export DOCKER_HOST=tcp://127.0.0.1:${PORT}"
    echo "export NO_PROXY=127.0.0.1,localhost"
    echo "export no_proxy=127.0.0.1,localhost"
    ;;
  *)
    echo "用法: $0 {up|down|env}" >&2
    exit 2
    ;;
esac
