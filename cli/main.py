"""CLI 入口：`agenty run "<任务>"`。见 docs/design.md §1.1（CLI 直连 SessionEngine，不经 HTTP）。

示例：
  # Claude 原生
  export ANTHROPIC_API_KEY=sk-...
  python -m cli.main run "修复失败的测试" --workspace examples/fix_failing_test --yes

  # DeepSeek（OpenAI 兼容端点）
  export DEEPSEEK_API_KEY=sk-...
  python -m cli.main run "<任务>" --provider openai --base-url https://api.deepseek.com \
    --model deepseek-chat --api-key-env DEEPSEEK_API_KEY --workspace <项目目录> --yes

默认沙箱 = local（开发友好）；接 Docker：--sandbox docker。默认审批 = 问一下；--yes 自动放行。
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tempfile

from core.engine import SessionEngine
from core.eval.harness import run_taskset
from core.eval.improve import improve
from core.eval.taskset import load_taskset
from core.eval.types import Policy
from core.harness.approval import ApprovalMode
from core.scenarios.coding.scenario import CodingScenario
from core.types import Message


def _text(msg: Message) -> str:
    return " ".join(b.text for b in msg.content if getattr(b, "type", "") == "text")


def _build_provider(args: argparse.Namespace):
    if args.provider == "openai":
        from core.providers.openai_compat import OpenAICompatProvider

        env = args.api_key_env or "OPENAI_API_KEY"
        key = os.environ.get(env)
        if not key:
            raise RuntimeError(f"未设置环境变量 {env}（OpenAI 兼容端点需要 API key）")
        return OpenAICompatProvider(api_key=key, base_url=args.base_url)

    from core.providers.anthropic import AnthropicProvider

    env = args.api_key_env or "ANTHROPIC_API_KEY"
    key = os.environ.get(env)
    if not key:
        raise RuntimeError(f"未设置环境变量 {env}")
    return AnthropicProvider(api_key=key)


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
        provider = _build_provider(args)
    except RuntimeError as e:
        print(f"⚠️  {e}\n    或离线体验：python scripts/demo_loop.py", file=sys.stderr)
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

    print(f"workspace: {workspace}\nprovider: {args.provider} · model: {args.model} · sandbox: {args.sandbox}\n")
    reason = "error"
    streaming = False  # 是否正在逐字打印一段助手文本
    async for ev in engine.submit(args.task):
        if ev.kind == "text_delta":
            if not streaming:
                print("🤖 ", end="", flush=True)
                streaming = True
            print(ev.text, end="", flush=True)
        elif ev.kind == "tool_use" and ev.tool_use is not None:
            streaming = False
            print(f"\n   → {ev.tool_use.name}({ev.tool_use.input})", flush=True)
        elif ev.kind == "tool_results" and ev.message is not None:
            streaming = False
            for b in ev.message.content:
                flag = "❌" if b.is_error else "✅"
                print(f"   {flag} {str(b.content)[:140]}")
        elif ev.kind == "done":
            reason = ev.reason or "done"
            print(f"\n🏁 {reason}")
    return 0 if reason == "completed" else 1


def _add_provider_args(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("--provider", choices=["anthropic", "openai"], default="anthropic")
    sp.add_argument("--base-url", help="OpenAI 兼容端点 base_url（如 DeepSeek: https://api.deepseek.com）")
    sp.add_argument("--api-key-env", help="读取 key 的环境变量名（默认 ANTHROPIC_API_KEY / OPENAI_API_KEY）")
    sp.add_argument("--model", default="claude-sonnet-4-6", help="模型 id（DeepSeek 用 deepseek-chat）")


async def _eval(args: argparse.Namespace) -> int:
    try:
        provider = _build_provider(args)
    except RuntimeError as e:
        print(f"⚠️  {e}", file=sys.stderr)
        return 1
    tasks = load_taskset(args.taskset)
    if not tasks:
        print(f"任务集为空: {args.taskset}", file=sys.stderr)
        return 2
    sc = CodingScenario()
    print(f"跑 {len(tasks)} 个任务 @ {args.model} …")
    run = await run_taskset(tasks, provider=provider, model=args.model, system=sc.system_prompt(), tools=sc.tools())
    for r in run.results:
        print(f"  {'✅' if r.passed else '❌'} {r.task_id}")
    n_pass = sum(1 for r in run.results if r.passed)
    print(f"\npass@1 = {run.pass_rate * 100:.0f}%  ({n_pass}/{len(run.results)})")
    return 0


async def _improve(args: argparse.Namespace) -> int:
    try:
        provider = _build_provider(args)
    except RuntimeError as e:
        print(f"⚠️  {e}", file=sys.stderr)
        return 1
    tasks = load_taskset(args.taskset)
    if len(tasks) < 2:
        print("自进化需要 ≥2 个任务（拆 train/val）", file=sys.stderr)
        return 2
    sc = CodingScenario()
    print(f"自进化一轮 @ {args.model} …（跑基线 + 据失败生成经验 + 验证集重跑）")
    rec, policy = await improve(tasks, provider=provider, model=args.model, base_policy=Policy(sc.system_prompt()), tools=sc.tools())
    print(f"\n基线 pass@1: {rec.baseline_pass * 100:.0f}%  →  候选: {rec.candidate_pass * 100:.0f}%  (Δ {rec.delta * 100:+.0f}pt)")
    print(f"改动: {rec.change_desc}")
    print(f"结论: {'✅ 保留（有提升）' if rec.kept else '↩️  回滚（无提升）'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="agenty", description="Agent Y CLI")
    sub = p.add_subparsers(dest="cmd")

    rp = sub.add_parser("run", help="跑一个编码任务")
    rp.add_argument("task", help='任务描述，如 "修复失败的测试"')
    rp.add_argument("--workspace", help="工作目录（默认临时目录）")
    _add_provider_args(rp)
    rp.add_argument("--sandbox", choices=["local", "docker"], default="local")
    rp.add_argument("--yes", action="store_true", help="自动放行写/危险操作（审批=AUTO）")

    ep = sub.add_parser("eval", help="跑任务集出 pass@1")
    ep.add_argument("--taskset", required=True, help="任务集目录，如 evals/coding-v1")
    _add_provider_args(ep)

    ip = sub.add_parser("improve", help="自进化一轮（据失败改进，仅当提升才保留）")
    ip.add_argument("--taskset", required=True, help="任务集目录")
    _add_provider_args(ip)

    args = p.parse_args(argv)
    if args.cmd == "run":
        return asyncio.run(_run(args))
    if args.cmd == "eval":
        return asyncio.run(_eval(args))
    if args.cmd == "improve":
        return asyncio.run(_improve(args))
    p.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
