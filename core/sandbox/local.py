"""LocalExecutor —— 宿主机执行器（DEV/测试用，实现 SandboxExecutor 接口）。

⚠️ 仅用于开发/测试。生产用 DockerSandbox（docker.py）——绝不在宿主机跑不可信代码（PRD F8.2）。
路径限制在 root 内（前缀校验，挡 `..` 越界）。
"""
from __future__ import annotations

import asyncio
import os

from core.sandbox.base import ExecResult


class LocalExecutor:
    def __init__(self, root: str):
        self.root = os.path.abspath(root)

    def _resolve(self, path: str) -> str:
        p = os.path.abspath(os.path.join(self.root, path))
        if p != self.root and not p.startswith(self.root + os.sep):
            raise ValueError(f"path escapes workspace: {path}")
        return p

    async def exec(
        self, cmd: list[str], cwd: str, timeout: int, network: bool = False
    ) -> ExecResult:
        workdir = self._resolve(cwd) if cwd and cwd != "." else self.root
        # PYTHONDONTWRITEBYTECODE：避免"改文件后同秒重跑测试时用到旧 .pyc 缓存"的坑
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=workdir, env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return ExecResult(exit_code=124, stdout="", stderr="timeout", timed_out=True)
        return ExecResult(
            exit_code=proc.returncode or 0,
            stdout=out.decode("utf-8", "replace"),
            stderr=err.decode("utf-8", "replace"),
        )

    async def write_files(self, files: dict[str, bytes]) -> None:
        for path, data in files.items():
            full = self._resolve(path)
            os.makedirs(os.path.dirname(full) or self.root, exist_ok=True)
            with open(full, "wb") as f:
                f.write(data)

    async def read_file(self, path: str) -> bytes:
        with open(self._resolve(path), "rb") as f:
            return f.read()
