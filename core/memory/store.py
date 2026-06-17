"""文件记忆：存储 / 召回 / 反思。见 docs/design.md §4.5（v1 无向量库、无 α/β/γ）。

存储：<project>/memory/<topic>.md（frontmatter name/description/type + 正文）；
MEMORY.md 索引常驻 system prompt。召回 = 扫 frontmatter → 小模型挑 ≤k 条。
"""
from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel


class Memory(BaseModel):
    name: str  # kebab-case slug = 文件名
    description: str  # 一句话，召回时给小模型判断相关性
    type: Literal["user", "feedback", "project", "reference"]
    body: str
    mtime: float | None = None  # 文件修改时间 → "saved N days ago" 文本


class MemoryStore(Protocol):
    async def recall(self, query: str, k: int = 5) -> list[Memory]: ...
    async def write(self, mem: Memory) -> None: ...  # 写 topic 文件 + 更新 MEMORY.md 索引
    def load_index(self) -> str: ...  # MEMORY.md 常驻 system prompt
