"""审批 / 沙箱分级（信任开关）。见 docs/design.md §5.1，落 PRD F8.4。

用户可见的信任分级，是核心 agent 体验的骨架（借鉴 Codex / Claude Code 的 allow/deny/ask）。
"""
from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from core.tools.base import PermissionResult


class ApprovalMode(Enum):
    READ_ONLY = "read_only"
    ASK = "ask"  # 默认：越权才停下确认
    AUTO = "auto"  # 不打断
    FULL = "full"  # 完全放开（仅可信环境）


class SandboxMode(Enum):
    READ_ONLY = "read_only"
    WORKSPACE_WRITE = "workspace_write"  # 默认：仓库内可改可跑、网络默认关
    FULL_ACCESS = "full_access"


def gate(perm: "PermissionResult", mode: ApprovalMode) -> Literal["allow", "deny", "ask"]:
    """据 ApprovalMode 调整工具权限决策。见 design §5.1。

    规则（TODO M1 Issue#8 实现）：
      - READ_ONLY 模式下写工具 → deny
      - AUTO → 把 ask 降为 allow（risk=high 除外）
      - is_destructive 或 risk=high → 强制 ask（不可逆/外发/写工作区外）
    """
    raise NotImplementedError  # 骨架桩
