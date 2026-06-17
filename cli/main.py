"""CLI 入口。M1 目标：`agenty run "<任务>"` 直连 SessionEngine（不经 HTTP）。

见 docs/design.md §1.1（CLI 可不经 HTTP 直接 import core）。
"""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help"):
        print('agenty — Agent Y CLI（骨架）\n  用法: agenty run "<任务>"   (TODO M1 Issue#11)')
        return 0
    if argv[0] == "run":
        print("[骨架] 将把任务交给 SessionEngine 跑 agent_loop。TODO(M1 Issue#11)。")
        return 0
    print(f"未知命令: {argv[0]}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
