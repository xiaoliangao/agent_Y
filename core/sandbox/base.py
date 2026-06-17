"""Sandbox 执行器接口。见 docs/design.md §4.4。

v1 = DockerSandbox（docker.py）。候选 = Java 执行器服务（同一接口，HTTP 实现）。
接口一致，所以换实现不动 tools。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False


class SandboxExecutor(Protocol):
    async def exec(
        self, cmd: list[str], cwd: str, timeout: int, network: bool = False
    ) -> ExecResult: ...
    async def write_files(self, files: dict[str, bytes]) -> None: ...
    async def read_file(self, path: str) -> bytes: ...
