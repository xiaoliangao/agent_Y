"""工具注册表 + 并发分桶执行。见 docs/design.md §4.3。

run_tools：对一批 tool_use 严格按"校验→权限→执行"跑；连续的并发安全工具并行、其余串行。
任何失败都回灌 is_error 的 tool_result（不抛异常中断 loop）。
"""
from __future__ import annotations

import asyncio
from typing import Callable

from pydantic import ValidationError

from core.harness.approval import gate
from core.obs.tracer import summarize
from core.tools.base import Tool, ToolContext
from core.types import ToolResultBlock, ToolUseBlock

_CONCURRENCY = 8


def _err(tool_use_id: str, msg: str) -> ToolResultBlock:
    return ToolResultBlock(
        tool_use_id=tool_use_id,
        content=f"<tool_use_error>{msg}</tool_use_error>",
        is_error=True,
    )


def _is_safe(tu: ToolUseBlock, tool: Tool | None) -> bool:
    if tool is None:
        return False
    try:
        inp = tool.input_model.model_validate(tu.input)
        return bool(tool.is_concurrency_safe(inp))
    except Exception:
        return False  # 解析失败一律当不安全


def _partition(tool_uses: list[ToolUseBlock], by_name: dict[str, Tool]) -> list[dict]:
    """把连续的"并发安全"工具分到同一批；非安全工具各自成批。"""
    batches: list[dict] = []
    for tu in tool_uses:
        safe = _is_safe(tu, by_name.get(tu.name))
        if safe and batches and batches[-1]["safe"]:
            batches[-1]["items"].append(tu)
        else:
            batches.append({"safe": safe, "items": [tu]})
    return batches


async def _run_one(
    tu: ToolUseBlock, by_name: dict[str, Tool], ctx: ToolContext,
    on_progress: Callable[[str], None],
) -> ToolResultBlock:
    with ctx.tracer.span(f"tool:{tu.name}", kind="tool", input=summarize(tu.input)) as tspan:
        block = await _run_one_inner(tu, by_name, ctx, on_progress)
        tspan.set(output=summarize(block.content), is_error=block.is_error)
        return block


async def _run_one_inner(
    tu: ToolUseBlock, by_name: dict[str, Tool], ctx: ToolContext,
    on_progress: Callable[[str], None],
) -> ToolResultBlock:
    tool = by_name.get(tu.name)
    if tool is None:
        return _err(tu.id, f"unknown tool: {tu.name}")

    # 1. 结构校验（Pydantic）
    try:
        inp = tool.input_model.model_validate(tu.input)
    except ValidationError as e:
        return _err(tu.id, f"InputValidationError: {e}")

    # 2. 语义校验
    v = await tool.validate_input(inp, ctx)
    if not v.ok:
        return _err(tu.id, v.message or "invalid input")

    # 3. 权限门（结合审批模式）
    perm = await tool.check_permissions(inp, ctx)
    decision = gate(perm, ctx.approval_mode)
    if decision == "deny":
        return _err(tu.id, "permission denied")
    if decision == "ask":
        ok = await ctx.request_approval(perm)
        if not ok:
            return _err(tu.id, "user denied the operation")

    # 4. 执行（失败也回灌错误，不抛）
    try:
        res = await tool.call(inp, ctx, on_progress)
    except Exception as e:  # noqa: BLE001
        return _err(tu.id, f"ToolExecutionError: {type(e).__name__}: {e}")
    return tool.to_model_result(res.data, tu.id)


async def run_tools(
    tool_uses: list[ToolUseBlock], by_name: dict[str, Tool], ctx: ToolContext,
    on_progress: Callable[[str], None] | None = None,
) -> list[ToolResultBlock]:
    progress = on_progress or (lambda _s: None)
    results: dict[str, ToolResultBlock] = {}
    for batch in _partition(tool_uses, by_name):
        items: list[ToolUseBlock] = batch["items"]
        if batch["safe"] and len(items) > 1:
            sem = asyncio.Semaphore(_CONCURRENCY)

            async def _guarded(tu: ToolUseBlock) -> ToolResultBlock:
                async with sem:
                    return await _run_one(tu, by_name, ctx, progress)

            done = await asyncio.gather(*[_guarded(tu) for tu in items])
            for tu, r in zip(items, done):
                results[tu.id] = r
        else:
            for tu in items:
                results[tu.id] = await _run_one(tu, by_name, ctx, progress)
    return [results[tu.id] for tu in tool_uses]
