"""DockerSandbox —— 在受限容器内执行（生产用）。见 docs/design.md §4.4 / PRD F8.2。

惰性 import docker SDK；容器默认关网络、限 CPU/内存；docker SDK 是同步的，用 asyncio.to_thread 包成异步。
模型生成的代码只在容器内跑，绝不上宿主机。

硬化（M1 收尾）：
- exec 超时：用容器内 `timeout` 命令强制 kill（exec_run 不支持超时），被杀 → exit 137 → timed_out=True。
- 网络放行：默认断网；构造传 network=True，或**首个 exec 请求 network 且容器尚未创建**时，
  起一个带网络的容器（容器级，创建后不可变；需联网装依赖的任务请尽早请求）。

⚠️ 无 Docker 环境用 core.sandbox.local.LocalExecutor 替代。
"""
from __future__ import annotations

import asyncio
import io
import shlex
import tarfile
import time
from pathlib import PurePosixPath
from typing import Any

from core.sandbox.base import ExecResult


def _timeout_cmd(cmd: list[str], timeout: int) -> list[str]:
    """把命令包进容器内 `timeout`，超时发 SIGKILL（被杀退出码 137）。timeout<=0 则不包。"""
    if timeout and timeout > 0:
        return ["timeout", "--signal=KILL", str(int(timeout)), *cmd]
    return cmd


class DockerSandbox:
    def __init__(
        self, image: str = "python:3.12-slim", workdir: str = "/workspace",
        mem_limit: str = "512m", cpus: float = 1.0, network: bool = False,
    ):
        self.image = image
        self.workdir = workdir
        self.mem_limit = mem_limit
        self.cpus = cpus
        self.network = network  # 容器级网络开关（默认关）
        self._container: Any = None
        self._exec_seq = 0

    def _ensure(self) -> Any:
        if self._container is None:
            try:
                import docker
            except ImportError as e:  # pragma: no cover
                raise RuntimeError("需要 docker SDK：pip install docker，且本机已装/启动 Docker") from e
            client = docker.from_env()
            self._container = client.containers.run(
                self.image, command="sleep infinity", detach=True, tty=True,
                network_disabled=not self.network, mem_limit=self.mem_limit,
                nano_cpus=int(self.cpus * 1e9), working_dir=self.workdir,
            )
            self._container.exec_run(["mkdir", "-p", self.workdir])
        return self._container

    def _exec_sync(self, cmd: list[str], cwd: str, timeout: int) -> ExecResult:
        c = self._ensure()
        workdir = cwd if cwd and cwd.startswith("/") else self.workdir
        # 输出重定向到容器内文件，命令结束后用 get_archive 拉回 —— 文件读取无流竞态。
        # 解决 exec_run(demux) 对极短命令的 attach 竞态（偶发空 stdout，网络延迟下尤甚）。
        self._exec_seq += 1
        tmp = f"/tmp/.agenty_exec_{self._exec_seq}"
        inner = shlex.join(_timeout_cmd(cmd, timeout))  # timeout 包住真实命令
        script = f"mkdir -p {tmp}; {inner} >{tmp}/out 2>{tmp}/err; echo -n $? >{tmp}/rc"
        c.exec_run(["sh", "-c", script], workdir=workdir, environment={"PYTHONDONTWRITEBYTECODE": "1"})
        files = self._read_dir(tmp)
        try:
            rc = int(files.get("rc", b"").decode().strip() or "-1")
        except ValueError:
            rc = -1
        return ExecResult(
            exit_code=rc,
            stdout=files.get("out", b"").decode("utf-8", "replace"),
            stderr=files.get("err", b"").decode("utf-8", "replace"),
            timed_out=(rc == 137),  # 137 = 128 + SIGKILL(9)，timeout 杀掉
        )

    def _read_dir(self, path: str) -> dict[str, bytes]:
        """get_archive 拉回目录下所有文件 → {basename: bytes}（无流竞态）。"""
        c = self._ensure()
        try:
            bits, _ = c.get_archive(path)
        except Exception:
            return {}
        buf = io.BytesIO(b"".join(bits))
        out: dict[str, bytes] = {}
        with tarfile.open(fileobj=buf) as tar:
            for member in tar.getmembers():
                if member.isfile():
                    f = tar.extractfile(member)
                    if f is not None:
                        out[PurePosixPath(member.name).name] = f.read()
        return out

    async def exec(self, cmd: list[str], cwd: str, timeout: int, network: bool = False) -> ExecResult:
        # 容器尚未创建且本次请求联网 → 让懒创建的容器带上网络（容器级，之后不可变）
        if network and not self.network and self._container is None:
            self.network = True
        return await asyncio.to_thread(self._exec_sync, cmd, cwd, timeout)

    def _put_sync(self, files: dict[str, bytes]) -> None:
        c = self._ensure()
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w") as tar:
            for path, data in files.items():
                info = tarfile.TarInfo(name=path.lstrip("/"))
                info.size = len(data)
                info.mtime = int(time.time())  # 真实 mtime：默认 0(1970) 会让改后的 .py 旧于 .pyc
                tar.addfile(info, io.BytesIO(data))
        stream.seek(0)
        c.put_archive(self.workdir, stream.read())

    async def write_files(self, files: dict[str, bytes]) -> None:
        await asyncio.to_thread(self._put_sync, files)

    def _get_sync(self, path: str) -> bytes:
        c = self._ensure()
        full = path if path.startswith("/") else f"{self.workdir}/{path}"
        bits, _ = c.get_archive(full)
        raw = b"".join(bits)
        with tarfile.open(fileobj=io.BytesIO(raw)) as tar:
            member = tar.getmembers()[0]
            f = tar.extractfile(member)
            return f.read() if f else b""

    async def read_file(self, path: str) -> bytes:
        return await asyncio.to_thread(self._get_sync, path)

    def close(self) -> None:
        if self._container is not None:
            try:
                self._container.remove(force=True)
            finally:
                self._container = None
