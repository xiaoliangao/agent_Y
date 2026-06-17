"""CLI 入口：`agenty run "<任务>"`。见 docs/design.md §1.1（CLI 直连 SessionEngine，不经 HTTP）。

示例：
  export ANTHROPIC_API_KEY=sk-...
  agenty run "修复 calculator.py 里失败的测试" --workspace ./examples/fix_failing_test
默认沙箱 = local（开发友好）；接 Docker：--sandbox docker。默认审批 = 问一下；--yes 自动放行。
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tempfile

from core.engine import SessionEngine
from core.harness.approval import ApprovalMode
from core.scenarios.coding.scenario import CodingScenario
from core.types import Message


def _text(msg: Message) -> str:
    return " ".join(b.text for b in msg.content if getattr(b, "type", "") == "text")


def _build_sandbox(kind: str, workspace: str):
    if kind == "docker":
        from core.sandbox.docker import DockerSandbox

        return DockerSandbox()
    from core.sandbox.local import LocalExecutor

    return LocalExecutor(workspace)


async def _run(args: argparse.Namespace) -> int:
    workspace = os.path.abspath(args.workspace or tempfile.mkdtemp(prefix="agenty-ws-"))
    if not os.path.isdir(workspace):
        print(f"workspace 不存在: {workspace}", file=sys.stderr)
        return 2

    try:
        from core.providers.anthropic import AnthropicProvider

        provider = AnthropicProvider()
    except Exception as e:  # noqa: BLE001
        print(f"初始化 provider 失败: {e}", file=sys.stderr)
        return 1
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("⚠️  未设置 ANTHROPIC_API_KEY，无法调用真实模型。\n"
              "    先 `export ANTHROPIC_API_KEY=sk-...`，或离线体验跑 `python scripts/demo_loop.py`。",
              file=sys.stderr)
        return 1

    scenario = CodingScenario()
    approval_mode = ApprovalMode.AUTO if args.yes else ApprovalMode.ASK

    async def ask(perm) -> bool:
        def _prompt() -> str:
            return input(f"\n⚠️  允许「{perm.summary or '该操作'}」? 风险={perm.risk} [y/N] ").strip().lower()

        return (await asyncio.to_thread(_prompt)) in ("y", "yes")

    engine = SessionEngine(
        provider=provider,
        tools=scenario.tools(),
        system=scenario.system_prompt(),
        sandbox=_build_sandbox(args.sandbox, workspace),
        model=args.model,
        approval_mode=approval_mode,
        request_approval=ask,
        transcript_path=os.path.join(workspace, "transcript.jsonl"),
    )

    print(f"workspace: {workspace}\nmodel: {args.model} · sandbox: {args.sandbox}\n")
    reason = "error"
    async for ev in engine.submit(args.task):
        if ev.kind == "assistant":
            if t := _text(ev.message):
                print(f"🤖 {t}")
            for b in ev.message.content:
                if getattr(b, "type", "") == "tool_use":
                    print(f"   → {b.name}({b.input})")
        elif ev.kind == "tool_results":
            for b in ev.message.content:
                flag = "❌" if b.is_error else "✅"
                print(f"   {flag} {str(b.content)[:120]}")
        elif ev.kind == "done":
            reason = ev.reason or "done"
            print(f"\n🏁 {reason}")
    return 0 if reason == "completed" else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="agenty", description="Agent Y CLI")
    sub = p.add_subparsers(dest="cmd")
    rp = sub.add_parser("run", help="跑一个编码任务")
    rp.add_argument("task", help="任务描述，如 \"修复失败的测试\"")
    rp.add_argument("--workspace", help="工作目录（默认临时目录）")
    rp.add_argument("--model", default="claude-sonnet-4-6", help="模型 id")
    rp.add_argument("--sandbox", choices=["local", "docker"], default="local")
    rp.add_argument("--yes", action="store_true", help="自动放行写/危险操作（审批=AUTO）")

    args = p.parse_args(argv)
    if args.cmd == "run":
        return asyncio.run(_run(args))
    p.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
