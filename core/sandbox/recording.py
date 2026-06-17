"""RecordingSandbox —— 透明记录文件改动，供 diff 审阅（PRD F5.1）。

包一层任意 SandboxExecutor：write_files 前先读旧内容，记下 {path: {old, new}}（old 取最早一次写之前的，
new 取最新）。exec/read_file 直接透传。不改工具，编码场景的 write_file/edit_file 改动即被捕获。
"""
from __future__ import annotations

from core.sandbox.base import ExecResult


class RecordingSandbox:
    def __init__(self, inner: object) -> None:
        self._inner = inner
        self.changes: dict[str, dict[str, str]] = {}  # path -> {"old", "new"}

    async def exec(self, cmd: list[str], cwd: str, timeout: int, network: bool = False) -> ExecResult:
        return await self._inner.exec(cmd, cwd, timeout, network)  # type: ignore[attr-defined]

    async def read_file(self, path: str) -> bytes:
        return await self._inner.read_file(path)  # type: ignore[attr-defined]

    async def write_files(self, files: dict[str, bytes]) -> None:
        for path, data in files.items():
            try:
                old = (await self._inner.read_file(path)).decode("utf-8", "replace")  # type: ignore[attr-defined]
            except Exception:
                old = ""  # 新建文件
            new = data.decode("utf-8", "replace") if isinstance(data, bytes) else str(data)
            if path in self.changes:
                self.changes[path]["new"] = new  # 多次写：old 保最早，new 更新
            else:
                self.changes[path] = {"old": old, "new": new}
        await self._inner.write_files(files)  # type: ignore[attr-defined]
