"""Tool 协议 + 上下文 + 结果类型。见 docs/design.md §4.3。

设计要点（抄 code-study-cc.md §3）：
  - input_model（Pydantic）= schema 来源，model_json_schema() 直接喂 API
  - fail-closed 默认：is_read_only/is_concurrency_safe/is_destructive 默认最保守
  - 两段式校验（形状 model_validate + 语义 validate_input），失败"回灌错误不抛"
  - call 返回纯数据 ToolResult.data；to_model_result(给模型) 与 render_for_ui(给trace) 是两个纯函数
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    Any,
    Awaitable,
    Callable,
    Generic,
    Literal,
    Protocol,
    TypeVar,
)

from pydantic import BaseModel

from core.types import ToolResultBlock

if TYPE_CHECKING:  # 仅类型，避免运行时循环 import
    from core.harness.approval import ApprovalMode
    from core.obs.tracer import Tracer
    from core.sandbox.base import SandboxExecutor


class ValidationResult(BaseModel):
    ok: bool
    message: str | None = None  # 失败时给模型的可读理由


class PermissionResult(BaseModel):
    behavior: Literal["allow", "deny", "ask"]
    risk: Literal["low", "medium", "high"] = "low"
    summary: str | None = None  # 给审批 UI 的一句话


class ToolResult(BaseModel):
    data: Any  # 纯数据 DTO（不是字符串、不是 UI 节点）


@dataclass
class ToolContext:
    """registry 注入给每个工具的上下文（core 内部，与 HTTP 无关）。"""

    cwd: str
    sandbox: "SandboxExecutor"
    abort: Any  # AbortSignal（M1 用 asyncio.Event 等价物）
    read_file_state: dict  # "先读后写"校验：edit 前必须先 read 过该文件
    approval_mode: "ApprovalMode"
    request_approval: Callable[[PermissionResult], Awaitable[bool]]  # behavior=ask 时调
    tracer: "Tracer"


TIn = TypeVar("TIn", bound=BaseModel)


class Tool(Protocol, Generic[TIn]):
    name: str
    input_model: type[TIn]

    def description(self) -> str: ...

    # —— fail-closed 默认 ——
    def is_read_only(self, inp: TIn) -> bool: ...        # 默认 False
    def is_concurrency_safe(self, inp: TIn) -> bool: ...  # 默认 = is_read_only
    def is_destructive(self, inp: TIn) -> bool: ...      # 默认 False

    # —— 两段式校验 + 权限 ——
    async def validate_input(self, inp: TIn, ctx: ToolContext) -> ValidationResult: ...
    async def check_permissions(self, inp: TIn, ctx: ToolContext) -> PermissionResult: ...

    # —— 执行 + 双重渲染 ——
    async def call(
        self, inp: TIn, ctx: ToolContext, on_progress: Callable[[str], None]
    ) -> ToolResult: ...
    def to_model_result(self, data: Any, tool_use_id: str) -> ToolResultBlock: ...  # 给模型
    def render_for_ui(self, data: Any) -> dict: ...  # 给 trace


class BaseTool(Generic[TIn]):
    """工具便捷基类：提供 fail-closed 默认 + 双重渲染默认。

    子类至少设 `name` / `input_model` + 实现 `call`；按需覆盖 is_read_only 等。
    """

    name: str = ""
    input_model: type[BaseModel]

    def description(self) -> str:
        return (self.__doc__ or self.name).strip()

    # —— fail-closed 默认 ——
    def is_read_only(self, inp: TIn) -> bool:
        return False

    def is_concurrency_safe(self, inp: TIn) -> bool:
        return self.is_read_only(inp)

    def is_destructive(self, inp: TIn) -> bool:
        return False

    async def validate_input(self, inp: TIn, ctx: "ToolContext") -> ValidationResult:
        return ValidationResult(ok=True)

    async def check_permissions(self, inp: TIn, ctx: "ToolContext") -> PermissionResult:
        if self.is_read_only(inp):
            return PermissionResult(behavior="allow", risk="low")
        risk = "high" if self.is_destructive(inp) else "medium"
        return PermissionResult(behavior="ask", risk=risk, summary=f"执行 {self.name}")

    async def call(
        self, inp: TIn, ctx: "ToolContext", on_progress: Callable[[str], None]
    ) -> ToolResult:
        raise NotImplementedError

    def to_model_result(self, data: Any, tool_use_id: str) -> ToolResultBlock:
        content = data if isinstance(data, str) else str(data)
        return ToolResultBlock(tool_use_id=tool_use_id, content=content)

    def render_for_ui(self, data: Any) -> dict:
        ok_types = (str, int, float, bool, dict, list)
        return {"result": data if isinstance(data, ok_types) else str(data)}
