"""DockerSandbox —— 在受限容器内执行（生产用）。见 docs/design.md §4.4 / PRD F8.2。

惰性 import docker SDK；容器默认关网络、限 CPU/内存；docker SDK 是同步的，用 asyncio.to_thread 包成异步。
模型生成的代码只在容器内跑，绝不上宿主机。

⚠️ 未在无 Docker 环境实测；开发/测试可用 core.sandbox.local.LocalExecutor 替代。
TODO(M1 收尾)：exec 超时强制 kill；容器复用与清理；put/get_archive 大文件流式。
"""
from __future__ import annotations

import asyncio
import io
import tarfile
from typing import Any

from core.sandbox.base import ExecResult


class DockerSandbox:
    def __init__(
        self, image: str = "python:3.12-slim", workdir: str = "/workspace",
        mem_limit: str = "512m", cpus: float = 1.0,
    ):
        self.image = image
        self.workdir = workdir
        self.mem_limit = mem_limit
        self.cpus = cpus
        self._container: Any = None

    def _ensure(self) -> Any:
        if self._container is None:
            try:
                import docker
            except ImportError as e:  # pragma: no cover
                raise RuntimeError("需要 docker SDK：pip install docker，且本机已装/启动 Docker") from e
            client = docker.from_env()
            self._container = client.containers.run(
                self.image, command="sleep infinity", detach=True, tty=True,
                network_disabled=True, mem_limit=self.mem_limit,
                nano_cpus=int(self.cpus * 1e9), working_dir=self.workdir,
            )
            self._container.exec_run(["mkdir", "-p", self.workdir])
        return self._container

    def _exec_sync(self, cmd: list[str], cwd: str) -> ExecResult:
        c = self._ensure()
        workdir = cwd if cwd and cwd.startswith("/") else self.workdir
        rc, output = c.exec_run(
            cmd, workdir=workdir, demux=True,
            environment={"PYTHONDONTWRITEBYTECODE": "1"},
        )
        out, err = output if isinstance(output, tuple) else (output, None)
        return ExecResult(
            exit_code=rc or 0,
            stdout=(out or b"").decode("utf-8", "replace"),
            stderr=(err or b"").decode("utf-8", "replace"),
        )

    async def exec(self, cmd: list[str], cwd: str, timeout: int, network: bool = False) -> ExecResult:
        # TODO: 用 timeout 强制 kill（exec_run 不直接支持，需 detach+轮询）
        return await asyncio.to_thread(self._exec_sync, cmd, cwd)

    def _put_sync(self, files: dict[str, bytes]) -> None:
        c = self._ensure()
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w") as tar:
            for path, data in files.items():
                info = tarfile.TarInfo(name=path.lstrip("/"))
                info.size = len(data)
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
