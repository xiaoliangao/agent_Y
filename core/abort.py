"""中断信号。loop 在"调模型前/工具前/工具内"查 .aborted。见 docs/design.md §1（abort）。"""
from __future__ import annotations

import asyncio


class AbortSignal:
    def __init__(self) -> None:
        self._event = asyncio.Event()

    def abort(self) -> None:
        self._event.set()

    @property
    def aborted(self) -> bool:
        return self._event.is_set()

    async def wait(self) -> None:
        await self._event.wait()
