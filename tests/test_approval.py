"""审批 gate() 单元测试。见 docs/design.md §5.1。"""
from __future__ import annotations

from core.harness.approval import ApprovalMode, gate
from core.tools.base import PermissionResult


def P(behavior: str, risk: str = "low") -> PermissionResult:
    return PermissionResult(behavior=behavior, risk=risk)


def test_read_only_allows_low_read():
    assert gate(P("allow", "low"), ApprovalMode.READ_ONLY) == "allow"


def test_read_only_denies_write():
    assert gate(P("ask", "medium"), ApprovalMode.READ_ONLY) == "deny"


def test_full_allows_all():
    assert gate(P("ask", "high"), ApprovalMode.FULL) == "allow"


def test_high_risk_forces_ask_even_in_auto():
    assert gate(P("ask", "high"), ApprovalMode.AUTO) == "ask"


def test_auto_downgrades_ask_to_allow():
    assert gate(P("ask", "medium"), ApprovalMode.AUTO) == "allow"


def test_ask_mode_keeps_behavior():
    assert gate(P("ask", "medium"), ApprovalMode.ASK) == "ask"
    assert gate(P("allow", "low"), ApprovalMode.ASK) == "allow"


def test_deny_stays_deny_in_auto():
    assert gate(P("deny", "low"), ApprovalMode.AUTO) == "deny"
