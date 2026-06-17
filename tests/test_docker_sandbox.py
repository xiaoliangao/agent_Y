"""DockerSandbox 真机测试（需本机 Docker daemon；无则整文件跳过）。

验证：写文件→执行命令读到→read_file 取回→能跑 python→默认断网。
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
