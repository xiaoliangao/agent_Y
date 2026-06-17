"""文件记忆：存储 / 召回 / 反思。见 docs/design.md §4.5（v1 无向量库、无 α/β/γ）。

存储：<root>/<name>.md（frontmatter name/description/type + 正文）；
<root>/MEMORY.md 索引常驻 system prompt。召回 = 扫 frontmatter → mtime 倒序候选 → 小模型挑 ≤k。
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel

from core.memory.recall import keyword_pick, llm_pick

MemoryType = Literal["user", "feedback", "project", "reference"]
_TYPES: tuple[str, ...] = ("user", "feedback", "project", "reference")
_MAX_CANDIDATES = 200
_FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.S)


class Memory(BaseModel):
    name: str  # kebab-case slug = 文件名
    description: str  # 一句话，召回时给小模型判断相关性
    type: MemoryType
    body: str
    mtime: float | None = None  # 文件修改时间 → "saved N days ago" 文本


class MemoryStore(Protocol):
    async def recall(self, query: str, k: int = 5) -> list[Memory]: ...
    async def write(self, mem: Memory) -> None: ...  # 写 topic 文件 + 更新 MEMORY.md 索引
    def load_index(self) -> str: ...  # MEMORY.md 常驻 system prompt


def _dump(mem: Memory) -> str:
    return (
        f"---\nname: {mem.name}\ndescription: {mem.description}\n"
        f"type: {mem.type}\n---\n\n{mem.body.strip()}\n"
    )


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    m = _FRONTMATTER.match(text)
    if not m:
        return {}, text
    fm: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            fm[key.strip()] = val.strip()
    return fm, m.group(2)


class FileMemoryStore:
    """MemoryStore 的文件实现。

    provider/model 给定时，recall 用小模型挑选；否则关键词兜底。
    也可注入 picker(query, candidates, k) -> list[name] 覆盖挑选逻辑（测试/自定义）。
    """

    def __init__(
        self,
        root: str,
        *,
        provider: object | None = None,
        model: str | None = None,
        picker: object | None = None,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.provider = provider
        self.model = model
        self._picker = picker
        self.index_path = self.root / "MEMORY.md"

    def _path(self, name: str) -> Path:
        return self.root / f"{name}.md"

    def load_index(self) -> str:
        return self.index_path.read_text(encoding="utf-8") if self.index_path.exists() else ""

    async def write(self, mem: Memory) -> None:
        self._path(mem.name).write_text(_dump(mem), encoding="utf-8")
        self._update_index(mem)

    def _update_index(self, mem: Memory) -> None:
        link = f"({mem.name}.md)"
        line = f"- [{mem.name}]{link} — {mem.description}"
        lines: list[str] = []
        if self.index_path.exists():
            lines = [ln for ln in self.index_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        lines = [ln for ln in lines if link not in ln]  # 同名去重
        lines.append(line)
        self.index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _scan(self) -> list[Memory]:
        """扫描所有记忆文件的 frontmatter + 正文，按 mtime 倒序取前 200 候选。"""
        mems: list[Memory] = []
        for p in self.root.glob("*.md"):
            if p.name == "MEMORY.md":
                continue
            try:
                fm, body = _parse_frontmatter(p.read_text(encoding="utf-8"))
            except OSError:
                continue
            if not fm.get("name"):
                continue
            mtype = fm.get("type", "reference")
            if mtype not in _TYPES:
                mtype = "reference"
            mems.append(
                Memory(
                    name=fm["name"],
                    description=fm.get("description", ""),
                    type=mtype,  # type: ignore[arg-type]
                    body=body.strip(),
                    mtime=p.stat().st_mtime,
                )
            )
        mems.sort(key=lambda m: m.mtime or 0.0, reverse=True)
        return mems[:_MAX_CANDIDATES]

    async def recall(self, query: str, k: int = 5) -> list[Memory]:
        candidates = self._scan()
        if not candidates:
            return []
        now = time.time()
        if self._picker is not None:
            names = await self._picker(query, candidates, k)  # type: ignore[operator]
        elif self.provider is not None and self.model:
            names = await llm_pick(self.provider, self.model, query, candidates, k, now)
        else:
            names = keyword_pick(query, candidates, k)
        by_name = {m.name: m for m in candidates}
        return [by_name[n] for n in names if n in by_name][:k]
