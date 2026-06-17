"""DockerSandbox 真机测试（需本机 Docker daemon；无则整文件跳过）。

验证：写文件→执行命令读到→read_file 取回→能跑 python→默认断网→超时强制 kill→放行网络。
对远程 daemon：export DOCKER_HOST=tcp://127.0.0.1:23750（隧道）+ NO_PROXY=127.0.0.1,localhost。
"""
from __future__ import annotations

import pytest

docker = pytest.importorskip("docker")


def _docker_ok() -> bool:
    try:
        docker.from_env().ping()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _docker_ok(), reason="需要可用的 Docker daemon")


async def test_docker_write_exec_read():
    from core.sandbox.docker import DockerSandbox

    sb = DockerSandbox()
    try:
        await sb.write_files({"hi.txt": b"hello docker"})

        res = await sb.exec(["cat", "hi.txt"], cwd=".", timeout=30)
        assert res.exit_code == 0
        assert "hello docker" in res.stdout

        data = await sb.read_file("hi.txt")
        assert data == b"hello docker"

        res2 = await sb.exec(["python3", "-c", "print(2 + 3)"], cwd=".", timeout=30)
        assert res2.stdout.strip() == "5"

        # 网络默认关：对外连接应失败
        res3 = await sb.exec(
            ["python3", "-c", "import socket; socket.create_connection(('1.1.1.1', 80), 2)"],
            cwd=".", timeout=30,
        )
        assert res3.exit_code != 0
    finally:
        sb.close()


async def test_docker_timeout_kills_long_command():
    from core.sandbox.docker import DockerSandbox

    sb = DockerSandbox()
    try:
        res = await sb.exec(["sleep", "10"], cwd=".", timeout=1)
        assert res.timed_out is True
        assert res.exit_code == 137  # 128 + SIGKILL
    finally:
        sb.close()


async def test_docker_network_enabled_allows_connection():
    from core.sandbox.docker import DockerSandbox

    sb = DockerSandbox(network=True)  # 放行网络
    try:
        res = await sb.exec(
            ["python3", "-c", "import socket; socket.create_connection(('1.1.1.1', 80), 3); print('ok')"],
            cwd=".", timeout=30, network=True,
        )
        assert "ok" in res.stdout
        assert res.exit_code == 0
    finally:
        sb.close()
