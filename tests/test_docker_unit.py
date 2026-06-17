"""DockerSandbox 纯逻辑单测（不需 Docker daemon）：超时包裹 + 网络开关。"""
from __future__ import annotations

from core.sandbox.base import ExecResult
from core.sandbox.docker import DockerSandbox, _timeout_cmd


def test_timeout_cmd_wraps():
    assert _timeout_cmd(["echo", "hi"], 30) == ["timeout", "--signal=KILL", "30", "echo", "hi"]
    assert _timeout_cmd(["x"], 0) == ["x"]  # 0/负数不包
    assert _timeout_cmd(["x"], -1) == ["x"]


def test_network_default_off_and_ctor_flag():
    assert DockerSandbox().network is False  # 默认断网
    assert DockerSandbox(network=True).network is True


async def test_network_escalates_before_container_created():
    sb = DockerSandbox()
    # 桩掉真实执行（无 daemon）；只验证 exec(network=True) 在容器未建时升级网络
    sb._exec_sync = lambda cmd, cwd, timeout: ExecResult(exit_code=0, stdout="", stderr="")
    await sb.exec(["echo"], cwd=".", timeout=10, network=True)
    assert sb.network is True
