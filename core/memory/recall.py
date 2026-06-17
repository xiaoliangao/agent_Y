"""记忆召回的挑选逻辑。见 docs/design.md §4.5、code-study-cc.md §6。

把候选记忆格式化成 manifest → 小模型挑 ≤k 条（确定相关才挑，可挑 0 条）；
无 provider 时退化为关键词重叠兜底。时近性以"saved N days ago"文本给模型（模型不擅长日期算术）。
"""
from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from core.llm import complete_text
from core.types import Message, TextBlock

if TYPE_CHECKING:  # 仅类型，避免 store↔recall 运行时循环 import
    from core.memory.store import Memory

_DAY = 86400.0


def humanize_age(mtime: float | None, now: float) -> str:
    """生成给模型看的时近性文本。"""
    if not mtime:
        return "saved recently"
    days = int((now - mtime) // _DAY)
    if days <= 0:
        return "saved today"
    if days == 1:
        return "saved 1 day ago"
    return f"saved {days} days ago"


def age_caveat(mtime: float | None, now: float) -> str:
    """>1 天的记忆附"可能过时"提醒。"""
    if mtime and (now - mtime) > _DAY:
        return "（可能已过时，断言前先核对）"
    return ""


def format_manifest(candidates: list["Memory"], now: float) -> str:
    return "\n".join(
        f"[{m.type}] {m.name} ({humanize_age(m.mtime, now)}): {m.description}" for m in candidates
    )


def keyword_pick(query: str, candidates: list["Memory"], k: int) -> list[str]:
    """离线兜底：按 query 词在 name+description 里的子串命中数打分，取前 k（无命中则空）。

    用子串而非整词重叠：CJK 无词边界，`\\w+` 会把整段中文切成一个 token，子串匹配更稳。
    """
    tokens = [t for t in re.findall(r"\w+", query.lower()) if t]
    if not tokens:
        return []
    scored: list[tuple[int, float, str]] = []
    for m in candidates:
        text = f"{m.name} {m.description}".lower()
        score = sum(1 for t in tokens if t in text)
        if score:
            scored.append((score, m.mtime or 0.0, m.name))
    scored.sort(reverse=True)
    return [name for _, _, name in scored[:k]]


_PICK_SYSTEM = """你是记忆挑选器。给你用户当前 query 和一份候选记忆清单（每行：[type] name (时近性): description）。
只挑出**确定**与 query 相关、能帮上忙的记忆（最多 {k} 条）；不确定就不挑，可以一条都不挑。
只输出一个 JSON 数组，元素是选中的 name 字符串，例如 ["foo","bar"]。不要任何解释。"""


async def llm_pick(
    provider: Any, model: str, query: str, candidates: list["Memory"], k: int, now: float
) -> list[str]:
    manifest = format_manifest(candidates, now)
    msg = Message(role="user", content=[TextBlock(text=f"Query: {query}\n\n候选记忆:\n{manifest}")])
    raw = await complete_text(
        provider, system=_PICK_SYSTEM.format(k=k), messages=[msg], model=model, max_tokens=256
    )
    names = _parse_name_array(raw)
    valid = {m.name for m in candidates}
    out: list[str] = []
    for n in names:
        if n in valid and n not in out:
            out.append(n)
    return out[:k]


def _parse_name_array(raw: str) -> list[str]:
    m = re.search(r"\[.*\]", raw, re.S)
    if not m:
        return []
    try:
        arr = json.loads(m.group(0))
    except Exception:
        return []
    return [x for x in arr if isinstance(x, str)]
