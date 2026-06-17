# Agent Y 技术设计文档（Design Doc）

| 项 | 值 |
|---|---|
| 文档版本 | v0.1（draft） |
| 状态 | 起草中 / 待 2 人 review |
| 上游依据 | `docs/PRD.md`(v0.3 功能与决策) · `docs/research.md`(技术选型依据) · `docs/code-study-cc.md`(行级借鉴清单) |
| 适用范围 | M1–M4 核心；M5/M6 仅粗线条 |
| 目标读者 | 作者 + 同事（2 人并行开发的接口契约依据） |

> **这份文档解决什么**：PRD 说"做什么"，design 说"怎么搭、谁负责哪块、模块之间怎么对话"。它的核心产出是**接口契约（§4）**——只要契约定死，两人就能各写一边、互不阻塞、最后能拼上。0 基础读者可把它当"施工图纸 + 学习地图"，每节都标了为什么这么设计。

---

## 0. 设计总原则（贯穿全文）

1. **两层切分**：纯逻辑的 `agent_loop`（不碰 DB/HTTP，可单测）与编排层 `SessionEngine`（持状态、选 Provider、写库、翻译成 API）。来源：`code-study-cc.md §1`（query.ts vs QueryEngine.ts 的干净边界）。
2. **接口先行**：所有跨模块调用走**显式接口（Protocol/ABC）+ 数据类（Pydantic）**；实现可换、可 mock。
3. **最简起步、按需加复杂度**：v1 单线程、不做向量库、不做多 Agent 并行；接口留好扩展位。来源：`research.md §C-14`。
4. **fail-closed 安全默认**：工具默认"会写、不可并发、需确认"；显式声明才放宽。来源：`code-study-cc.md §3`。
5. **错误即消息**：工具/校验失败不抛异常中断 loop，而是包成 `is_error` 的 tool_result 回灌模型自纠。来源：`code-study-cc.md §1/§3`。

---

## 1. 架构总览

### 1.1 进程与客户端拓扑

```
┌──────────────────────────── 桌面外壳 (pywebview → .app) ─────────────────────────────┐
│  ┌───────────────┐   ┌───────────────────┐   ┌──────────────────────────────────┐   │
│  │ Web 前端 (JS)  │   │ 内嵌终端 (兼容CLI) │   │  CLI (独立可用，一等公民)          │   │
│  │ chat + trace  │   │                   │   │                                  │   │
│  └───────┬───────┘   └─────────┬─────────┘   └──────────────┬───────────────────┘   │
│          │ HTTP / SSE          │ 调本地后端                  │ 直接 import core / 或走 HTTP │
└──────────┼─────────────────────┼─────────────────────────────┼──────────────────────┘
           ▼                     ▼                             ▼
   ┌─────────────────────────────────────────────────────────────────────┐
   │              本地后端服务  (FastAPI, 127.0.0.1, 单用户)                 │
   │   server/ —— REST + SSE 路由层（仅做 HTTP↔SessionEngine 翻译）          │
   ├─────────────────────────────────────────────────────────────────────┤
   │   core/  —— SessionEngine ── agent_loop ── { providers, tools,        │
   │             harness(context/approval), memory, obs, eval, scenarios } │
   └───────────────┬───────────────────────────────┬─────────────────────┘
                   ▼                               ▼
          ┌──────────────────┐            ┌─────────────────────────┐
          │ Docker 沙箱执行器  │            │ 存储: SQLite + 文件       │
          │ (代码/测试)        │            │ (会话/trace/记忆/eval)    │
          │ ※ 候选: Java 服务  │            │ + Langfuse(自托管)        │
          └──────────────────┘            └─────────────────────────┘
```

**关键点**：
- **后端是唯一真相源**，CLI / GUI / 内嵌终端都只是它的客户端（对应 PRD §2.4"核心解耦 GUI"）。
- **CLI 可不经 HTTP 直接 `import core`** 跑（M1 就是这样，最简）；GUI 走 HTTP/SSE。两条路共用同一个 `SessionEngine`。
- 密钥存 OS keychain，**只有 keychain 引用进 DB**，绝不明文落库（PRD F8.1）。

### 1.2 一次请求的数据流（端到端）

```
用户在 GUI 输入
  → POST /sessions/{id}/messages           (server 路由层)
  → SessionEngine.submit(text)             (编排：拼 system+context、选 provider)
      → agent_loop(state)                  (纯循环)
          loop:
            provider.stream(...)           → 归一化事件流 (text/thinking/tool_use/usage)
            有 tool_use? → run_tools(...)   → 校验→权限(可能触发 approval_request)→执行→tool_result
            无 tool_use? → 结束
          每一步 yield 事件 + 写 span
  → SessionEngine 把事件翻译成 SSE 帧
  → server 以 text/event-stream 推给前端
  → 前端左栏渲染 chat、右栏渲染 trace
```

---

## 2. 模块边界与职责

| 模块 | 路径 | 职责 | 依赖 | 不该做 |
|---|---|---|---|---|
| **types** | `core/types.py` | 全局数据类型（Message/ContentBlock/ToolUse/ToolResult/Usage/Span…） | 无 | 不含逻辑 |
| **loop** | `core/loop.py` | 纯 act-observe 循环（generator） | types, providers(接口), tools(接口) | 不碰 DB/HTTP/UI |
| **engine** | `core/engine.py` | 会话编排：组 system+context、选 provider、调 loop、写库、翻译事件 | 全部 | 不写具体 provider/tool 逻辑 |
| **providers** | `core/providers/` | LLM 适配：把各家 API 归一成统一流式事件 | types | 不碰业务 |
| **tools** | `core/tools/` | 工具协议 + 内置工具 + 注册表 + 并发分桶执行 | types, sandbox, approval | 不直接调模型 |
| **harness** | `core/harness/` | 上下文管理（估算/压缩/清理）+ 审批/沙箱分级 | types | — |
| **memory** | `core/memory/` | 文件记忆：写入/召回(小模型挑)/反思沉淀 | types, providers | v1 不做向量库 |
| **obs** | `core/obs/` | Tracer 接口 → Langfuse/console | types | — |
| **eval** | `core/eval/` | 任务集跑分 + 自进化（候选→验证→留升） | 全部 | — |
| **sandbox** | `core/sandbox/` | Docker 执行器（候选 Java 服务） | — | — |
| **scenarios** | `core/scenarios/` | 场景插件（coding 先；assistant 后） | tools | 不改内核 |
| **server** | `server/` | FastAPI REST+SSE，仅翻译 HTTP↔Engine | core | 不含 agent 逻辑 |
| **cli** | `cli/` | 命令行入口 | core 或 server | — |

> **解耦的好处（讲给 0 基础）**：每个模块只通过"接口 + 数据类"和别人说话。同事改 `sandbox` 的内部实现，只要不改它的接口签名，你的 `tools` 完全不用动。这就是两人能并行的根本。

---

## 3. 核心数据类型（`core/types.py`）

统一用 **Pydantic v2**（既做校验、又能 `model_json_schema()` 直接喂 API）。归一化到 **Anthropic 风格的 content blocks**（OpenAI 格式在 provider adapter 层转换）。

```python
from pydantic import BaseModel
from typing import Literal, Any
from enum import Enum

# ---------- 内容块（content blocks）----------
class TextBlock(BaseModel):
    type: Literal["text"] = "text"
    text: str

class ThinkingBlock(BaseModel):
    type: Literal["thinking"] = "thinking"
    thinking: str

class ToolUseBlock(BaseModel):
    type: Literal["tool_use"] = "tool_use"
    id: str
    name: str
    input: dict[str, Any]

class ToolResultBlock(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: str | list[dict]          # 文本或多模态
    is_error: bool = False

ContentBlock = TextBlock | ThinkingBlock | ToolUseBlock | ToolResultBlock

# ---------- 消息 ----------
class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: list[ContentBlock]

class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    # 可扩展 cache_read / cache_write

# ---------- 归一化的流式事件（provider 吐给 loop）----------
class StreamEvent(BaseModel):
    type: Literal[
        "text_delta", "thinking_delta",
        "tool_use",        # 一个完整的 tool_use 块（input 已 parse）
        "message_done",    # 带 usage + stop_reason
    ]
    text: str | None = None
    tool_use: ToolUseBlock | None = None
    usage: Usage | None = None
    stop_reason: str | None = None     # 仅记录/调试用，不作为停止主信号
```

> **设计说明**：`StreamEvent` 是 provider 与 loop 之间的契约。每家 API 流式格式不同（见 `code-study-cc.md §1` 的"accumulate-then-finalize"），但**统一在 adapter 里拼成"tool_use 块结束才整块吐出（input 已 `json.loads`）"**，loop 永远只面对这一种事件。

---

## 4. 接口契约（完整规范 · 冻结面）

> **冻结规则**：本节是两人编码的**唯一接口真相源**。任何改动 → PR 标题带 `[contract]` + @ 对方 + 合并前双方确认。**先冻结，再各写各的、用 mock 对接。**
> **怎么读**：§4.0 通用约定；§4.1 前后端 HTTP/SSE（前端/同事侧关心）；§4.2–4.5 是 core 内部 Python 接口（后端侧关心）。

### 4.0 通用约定
- **传输**：后端绑 `127.0.0.1:<port>`，**单用户、本地无鉴权**（不监听外网）。请求/响应 `application/json; charset=utf-8`。
- **时间**：一律 ISO-8601 UTC（`2026-06-17T08:30:00Z`）。
- **ID 前缀**：`sess_`(会话) `msg_` `span_` `appr_`(审批) `task_` `run_`(eval) `conn_`(provider 连接)；`tool_use.id` 由模型给、原样透传。
- **错误信封**（所有非 2xx）：`{ "error": { "code": "session_not_found", "message": "人类可读", "detail": {} } }`。常用 code：`bad_request`(400) / `not_found`(404) / `conflict`(409) / `provider_error`(502) / `internal`(500)。
- **流式**：仅 `POST /sessions/{id}/messages` 用 SSE（`text/event-stream`），其余都是普通 JSON。

### 4.1 后端 ↔ 前端（FastAPI REST + SSE）

#### 4.1.1 REST 端点（逐个完整规范）

**会话**
- `POST /sessions` — 新建会话/线程
  - 请求 `{ "title"?: string, "scenario"?: "coding"|"assistant" }`
  - 响应 `201` `{ "session_id", "title", "scenario", "created_at" }`
- `GET /sessions` — 列会话（updated_at 倒序）→ `{ "sessions": [ {"id","title","scenario","status","updated_at","message_count"} ] }`；`status` ∈ `idle|running|error`
- `GET /sessions/{id}` — 详情 + 历史 → `{ "session": {..}, "messages": [Message,..] }`（Message 见 §3）；`404 session_not_found`
- `DELETE /sessions/{id}` — 删会话连带 transcript → `200 {ok:true}`

**对话（核心，SSE）**
- `POST /sessions/{id}/messages` — 发用户消息，**返回 SSE 流**
  - 请求 `{ "text": string, "attachments"?: [ {type,...} ] }`
  - 成功 `200` + `Content-Type: text/event-stream`，随后是 §4.1.2 事件序列，以 `done` 结束
  - 流前失败 `409 conflict`（已有 running）/ `404` / `400`；流中出错 → 发 `error` 事件再 `done{reason:"error"}`

**审批 / 中断**
- `POST /approvals/{approval_id}` — `{ "decision":"allow"|"deny", "scope"?:"once"|"session" }`（`session`=本会话内同类自动放行）→ `200 {ok:true}`；`409 approval_expired`
- `POST /sessions/{id}/interrupt` — 中断当前运行（abort）→ `200 {ok:true}`

**Trace**
- `GET /sessions/{id}/trace` — `{ "spans": [Span,..] }`（Span 见 §7，含 parent_id 可重建树）

**Provider / 模型（BYOK）**
- `GET /providers` — 列连接（**绝不返回 key**）→ `{ "connections": [ {"id","provider","base_url"?,"model_default"?,"created_at"} ] }`
- `POST /providers` — `{ "provider":"anthropic"|"openai_compat", "api_key":string, "base_url"?, "model_default"? }`；**key 立即进 OS keychain，DB 仅存 keychain_ref、响应不回显 key** → `201 { "id":"conn_..","provider","base_url"?,"model_default"? }`
- `DELETE /providers/{id}` — 连带删 keychain 项 → `200 {ok:true}`
- `GET /models` — `{ "models": [ {"id","provider","context_window","max_output","supports_tools","supports_thinking","price_in"?,"price_out"?} ] }`

**Eval / 后台任务**
- `POST /eval/runs` — `{ "taskset":string, "model":string }` → `202 { "run_id" }`（异步）
- `GET /eval/runs/{id}` — `{ "run_id","taskset","model","status","pass_rate"?,"results":[{task_id,passed,detail}],"curve"? }`
- `GET /tasks/{id}` — `{ "id","type","status","description","output_file"?,"created_at","ended_at"? }`；status ∈ `pending|running|completed|failed|killed`

#### 4.1.2 SSE 事件目录（完整字段）
每帧 = `data: <一行 JSON>\n\n`；前端按 `type` 分发：

| type | 字段 | 时机 / 渲染 |
|---|---|---|
| `text_delta` | `text` | 助手文本增量 → 左栏 chat |
| `thinking_delta` | `text` | 思考增量 → 可折叠区 |
| `tool_use` | `id, name, input(object)` | 模型决定调工具（input 已 parse 完整）→ trace 新节点 |
| `tool_progress` | `id, chunk` | 工具执行中流式进度（如 bash 输出）|
| `tool_result` | `id, is_error(bool), preview` | 工具结束（preview 截断；全文在 trace/transcript）|
| `approval_request` | `approval_id, tool, summary, risk("low"/"medium"/"high")` | **暂停**等 `POST /approvals`；UI 弹确认 |
| `span` | `span(Span 见 §7)` | trace 节点增量 → 右栏 |
| `usage` | `input_tokens, output_tokens` | 本轮用量（可累加成本）|
| `done` | `reason("completed"/"max_turns"/"aborted"/"error")` | **流终结** |
| `error` | `message, code?` | 出错（其后必跟 `done{reason:"error"}`）|

> 前端只认这 10 种事件，后端实现随意演进。`approval_request` = **服务端发起、暂停等回复**的审批门（借鉴 Codex App Server，`research.md §C-24`）。

#### 4.1.3 一次对话时序（示例）
```text
前端 → POST /sessions/sess_1/messages {text:"修复失败的测试"}
后端 ← 200 text/event-stream:
   span(run开始) → thinking_delta* → text_delta*
   → tool_use(bash,{cmd:"pytest"}) → tool_progress* → tool_result(...)
   → tool_use(edit_file,...) → approval_request(appr_9, write_file, "改1个文件", medium)   [暂停]
前端 → POST /approvals/appr_9 {decision:"allow"}
后端 ← (续) tool_result(...) → text_delta*("已修复…") → usage → done(completed)
```

### 4.2 core ↔ Provider（`core/providers/base.py`）

```python
from typing import Protocol, AsyncIterator
from core.types import Message, StreamEvent

class LLMProvider(Protocol):
    name: str
    async def stream(
        self,
        *,
        system: str,
        messages: list[Message],
        tools: list[dict],            # 每个 = tool.input_model.model_json_schema() 包装
        max_tokens: int,
        model: str,
        extra: dict | None = None,    # thinking/effort 等 provider 特有项
    ) -> AsyncIterator[StreamEvent]: ...

    def count_tokens(self, messages: list[Message]) -> int | None: ...
        # 能精确就精确(对端 usage / tiktoken)，否则返回 None 让 harness 用粗估
```

实现：
- **`AnthropicProvider`**（M1）：用 `anthropic` SDK 的 `messages.stream`；按 `code-study-cc.md §1` 解析 SSE。注意用 `thinking:{type:"adaptive"}` + `output_config:{effort}`，**不要传 `temperature`/`top_p`/`budget_tokens`**（见 `claude-api` 约定）。
- **`OpenAICompatProvider`**（M3）：用 `openai` SDK 指 `base_url`，覆盖 GPT/DeepSeek/Ollama/LM Studio。把 OpenAI 的 `tool_calls`/`delta` 流**转成统一 `StreamEvent`**；tool_result 以 `role:"tool"` 回发；无 server 端上下文管理原语（见 §5）。

**`stream` 的契约保证**（loop 依赖，adapter 必须遵守）：
1. 事件顺序 `(text_delta | thinking_delta | tool_use)* → message_done`。
2. **`tool_use` 只在该块完整、`input` 已 `json.loads` 后吐出**（分片 JSON 在 adapter 内累积，`code-study-cc.md §1`）。
3. `message_done` 必带 `usage` 与 `stop_reason`（后者仅记录/调试，**不作停止主信号**）。
4. 收到 abort → 停止产出、清理连接、抛 `Aborted`；API 错误（限流/超时/鉴权）→ 抛 `ProviderError(code, retryable)`，**不静默吞**，由 loop 决定重试/上报。

> **契约要点**：loop 只依赖 `LLMProvider` 这个 Protocol，**永远不 import 具体 provider**。加一家 = 写一个 adapter，不动 loop。

### 4.3 core ↔ Tool（`core/tools/base.py`）

抄 `code-study-cc.md §3` 的契约，Python 化：

```python
from typing import Protocol, Generic, TypeVar, Any, AsyncIterator
from pydantic import BaseModel

class ValidationResult(BaseModel):
    ok: bool
    message: str | None = None        # 失败时给模型的可读理由

class PermissionResult(BaseModel):
    behavior: Literal["allow", "deny", "ask"]
    risk: Literal["low", "medium", "high"] = "low"
    summary: str | None = None        # 给审批 UI 的一句话

TIn = TypeVar("TIn", bound=BaseModel)

class ToolResult(BaseModel, Generic[...]):
    data: Any                         # 纯数据 DTO（不是字符串/不是 UI）
    # 可选: context_modifier

class Tool(Protocol, Generic[TIn]):
    name: str
    input_model: type[TIn]            # Pydantic = schema 来源
    def description(self) -> str: ...
    # —— 安全默认 fail-closed ——
    def is_read_only(self, inp: TIn) -> bool: ...        # 默认 False
    def is_concurrency_safe(self, inp: TIn) -> bool: ... # 默认 = is_read_only
    def is_destructive(self, inp: TIn) -> bool: ...      # 默认 False
    # —— 两段式校验 + 权限 ——
    async def validate_input(self, inp: TIn, ctx) -> ValidationResult: ...
    async def check_permissions(self, inp: TIn, ctx) -> PermissionResult: ...
    # —— 执行 + 双重渲染 ——
    async def call(self, inp: TIn, ctx, on_progress) -> ToolResult: ...
    def to_model_result(self, data, tool_use_id: str) -> ToolResultBlock: ...  # 给模型
    def render_for_ui(self, data) -> dict: ...                                  # 给 trace
```

**`ToolContext`**（registry 注入给每个工具，是 core 内部 ctx，与 4.1 的 HTTP 无关）：
```python
@dataclass
class ToolContext:
    cwd: str
    sandbox: SandboxExecutor
    abort: AbortSignal
    read_file_state: dict                # "先读后写"校验：edit 前必须先 read 过该文件
    approval_mode: ApprovalMode
    request_approval: Callable[[PermissionResult], Awaitable[bool]]  # behavior=ask 时调(触发 SSE)
    tracer: Tracer
```

**生命周期**（`registry` 对每个 tool_use 严格按序；任何失败都"回灌错误、不抛异常中断 loop"）：
1. `input_model.model_validate(raw)` 失败 → 回 `tool_result{is_error:true, content:"<tool_use_error>InputValidationError: .."}`。
2. `validate_input` 失败 → 同样回 `<tool_use_error>`。
3. `check_permissions`：`deny`→回 error；`ask`→`ctx.request_approval`（触发 SSE `approval_request` 暂停），拒绝→回 error。
4. `call(inp, ctx, on_progress)` → `ToolResult(data=..)`；`on_progress(chunk)` 推 `tool_progress`。
5. `to_model_result` 拼回历史，`render_for_ui` 进 trace。

**并发**：连续 `is_concurrency_safe=True` 的工具 `asyncio.gather` 并行（`Semaphore(8)`），写工具串行；并行批内 context 修改先收集、跑完统一应用（`code-study-cc.md §1`）。

**M1 内置工具**：`bash`(非只读) · `read_file`/`grep`/`glob`(只读) · `write_file`/`edit_file`(写；`edit_file` 要求先 read 过该文件，PRD F2.3)。

### 4.4 core ↔ Sandbox（`core/sandbox/base.py`）

```python
@dataclass
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False

class SandboxExecutor(Protocol):
    async def exec(self, cmd: list[str], cwd: str, timeout: int,
                   network: bool = False) -> ExecResult: ...      # stdout/stderr/exit_code
    async def write_files(self, files: dict[str, bytes]) -> None: ...
    async def read_file(self, path: str) -> bytes: ...
```

- **v1 `DockerSandbox`**（Python，M1）：每个编码任务起一个受限容器（关网络、限 CPU/内存/时长），模型生成的代码**只在容器内跑**（PRD F8.2）。
- **候选 `JavaSandboxService`**（M5，同事可负责）：把上面接口实现成一个 **Spring Boot HTTP 服务**（`POST /exec`），Python 侧写个 HTTP client 适配 `SandboxExecutor`。**接口一致，所以换实现不动 tools**。这是 Java 落点之一（PRD §13）。

### 4.5 core ↔ Memory（`core/memory/store.py`）

按 `code-study-cc.md §6` 校准后的文件方案（**v1 无向量库、无 α/β/γ**）：

```python
class Memory(BaseModel):
    name: str                            # kebab-case slug = 文件名
    description: str                     # 一句话，召回时给小模型判断相关性
    type: Literal["user", "feedback", "project", "reference"]
    body: str
    mtime: float | None = None           # 文件修改时间 → "saved N days ago" 文本

class MemoryStore(Protocol):
    async def recall(self, query: str, k: int = 5) -> list["Memory"]: ...
        # 扫各文件 frontmatter → 小模型挑 ≤k 条 → 读出，附 "saved N days ago"
    async def write(self, mem: "Memory") -> None: ...      # 写 topic 文件 + 更新 MEMORY.md 索引
    def load_index(self) -> str: ...                       # MEMORY.md 常驻 system prompt
```

- 存储：`<project>/memory/<topic>.md`（frontmatter `name/description/type` + 正文）；`MEMORY.md` 索引常驻。
- 类型（四类）：`user / feedback / project / reference`。
- 召回：mtime 倒序截断候选 → 便宜模型挑 ≤5（不确定不选）。
- 反思沉淀：每轮结束 fork 一个**受限子 agent**（只读 + 只能写 memory 目录、限 turn、强制先查重）。

---

## 5. 上下文管理设计（harness 层，`core/harness/context.py`）

> **为什么单列一节**：Claude 原生有 server 端压缩原语，但 BYOK 的 OpenAI 兼容端点**没有**，必须自己实现。配方全部来自 `code-study-cc.md §2`（纯客户端代码，Python 可 1:1 复刻）。

```python
class ContextManager:
    def estimate(self, messages) -> int:
        # 锚点+增量：从尾部找最近一条带真实 usage 的 assistant 消息为锚，只粗估其后新增
        # 粗估 len/4（JSON /2、图片固定 2000），结果 *4/3 保守高估
    def maybe_compact(self, messages, model_window) -> list[Message]:
        effective = model_window - min(max_output, 20_000)   # 预留摘要输出
        if est >= effective - 13_000:   return self._full_compact(messages)
        if est >= effective * 0.6:      return self._clear_tool_results(messages)
        return messages
    def _clear_tool_results(self, messages):
        # 白名单工具(read/bash/grep/...)的旧结果, 保留最近 KEEP_RECENT=5 个,
        # 其余 content 换成 "[Old tool result content cleared]"
    def _full_compact(self, messages):
        # 同模型发一次"禁工具单轮"请求，用 9 段式摘要提示词（见 code-study §2），
        # 事后正则剥 <analysis>；保留最近 ≥10k token 且 ≥5 条文本(上限 40k)，
        # 切点绝不切断 tool_use/tool_result 配对；摘要附 "完整记录见 transcript 路径"
```

- **熔断**：连续 3 次压缩失败就停（防 runaway）。
- **能用第一方机制则用**：Anthropic 原生 compaction / Responses API `previous_response_id`（Tau-Bench +4.3pt，`research.md §C-22`）能用就用，不能则退回上面自管逻辑。

### 5.1 审批 / 沙箱分级（`core/harness/approval.py`，落 PRD F8.4）

```python
class ApprovalMode(Enum):  READ_ONLY; ASK; AUTO; FULL      # 只读/问一下(默认)/自动/完全放开
class SandboxMode(Enum):   READ_ONLY; WORKSPACE_WRITE; FULL_ACCESS  # 默认 WORKSPACE_WRITE+断网

def gate(tool, inp, mode) -> PermissionResult:
    # 1. tool.check_permissions 给出 allow/deny/ask + risk
    # 2. 按 ApprovalMode 调整：READ_ONLY 模式下写工具→deny；AUTO→把 ask 降为 allow（除 high risk）
    # 3. is_destructive 或 risk=high → 强制 ask（不可逆/外发/写工作区外）
```

UI 暴露为可见开关（M2）。来源：`research.md §C-24`（guardrail 并行 + tripwire + 工具风险分级 + 审批暂停门）。

---

## 6. 可观测 / Eval / 自进化（接口骨架）

### 6.1 Tracer（`core/obs/tracer.py`）
```python
class Tracer(Protocol):
    def span(self, name: str, parent: str | None, **attrs) -> "SpanCtx": ...  # run→llm/tool/decision
```
- M1 `ConsoleTracer`；M2 `LangfuseTracer`（自托管）。每个 span 记输入输出摘要/token/延迟/父子关系（PRD F3.1）。
- **设计取舍**：span 树结构 = trace 落库 schema = 未来喂自进化的 eval 样本来源（待补：trace→eval 样本映射，`research.md §④-4`）。

### 6.2 Eval + 自进化（`core/eval/`）
- **任务集**：每个任务 = `{workspace 目录, 测试命令, 评分脚本}`，跑出 `pass@1`（PRD F4.1）。
- **自进化循环**（`research.md §自进化`）：跑基线 → 失败聚类归因 → 生成改进候选（改 system prompt 片段 / 加 few-shot 记忆 / 调工具 description）→ 在**留出验证集**重跑 → **仅当通过率提升才保留，否则回滚** → 出提升曲线 + 可解释改进记录（PRD F4.2）。

---

## 7. 数据模型与存储

**存储分工**：SQLite（结构化元数据，单文件 `agenty.db`）+ 文件系统（记忆 md、每会话 JSONL transcript）+ Langfuse（trace 可视，自托管）。密钥只进 OS keychain。

```
SQLite 表（v1）:
  sessions(id, title, scenario, created_at, updated_at, status)
  messages(id, session_id, seq, role, content_json, usage_json, created_at)
  spans(id, session_id, parent_id, name, kind, input_summary, output_summary,
        tokens, latency_ms, started_at, ended_at)
  tasks(id, type, status, description, output_file, created_at, ended_at)   # 后台/异步
  eval_runs(id, taskset, model, pass_rate, created_at)
  eval_results(id, run_id, task_id, passed, detail_json)
  improvements(id, run_before, run_after, change_desc, kept: bool, rollback_ref)
  provider_connections(id, provider, base_url, model_default, keychain_ref)  # 无明文 key

文件系统:
  <project>/memory/<topic>.md         # 记忆（md + frontmatter）
  <project>/memory/MEMORY.md          # 记忆索引（常驻 system prompt）
  <session>/transcript.jsonl          # 全量消息流水（可回放，仿 cc-resourcecode）
  agents/<name>.md                    # 子 agent 定义（frontmatter + 正文）
  skills/<name>/SKILL.md              # 技能（渐进披露）
  AGENTS.md                           # 给 agent 的"地图"（见 §8.3）
```

> **取舍说明**：消息既进 SQLite（便于查询/分页）又进 JSONL transcript（全保真、可回放、压缩时做"逃生舱"）。v1 不引向量库；记忆量大到挑选不准时再加 sqlite-vec（`research.md §Memory 演进路径`）。

---

## 8. 工程：目录结构 / 选型 / 协作规范

### 8.1 目录结构
```
agent_y/
├── core/
│   ├── types.py
│   ├── loop.py            engine.py
│   ├── providers/         base.py  anthropic.py  openai_compat.py
│   ├── tools/             base.py  registry.py  bash.py read.py write.py edit.py
│   ├── harness/           context.py  approval.py
│   ├── memory/            store.py  recall.py  reflect.py
│   ├── obs/               tracer.py  langfuse.py
│   ├── eval/              harness.py  improve.py
│   ├── sandbox/           base.py  docker.py
│   └── scenarios/         coding/   assistant/(后)
├── server/                app.py  routes/
├── cli/                   main.py
├── frontend/              (M2，Web)
├── agents/  skills/       (定义文件)
├── tests/
├── pyproject.toml         AGENTS.md  README.md
└── docs/                  PRD.md research.md code-study-cc.md design.md
```

### 8.2 技术选型确认（锁定）
| 层 | 选型 |
|---|---|
| 语言/运行时 | Python 3.12+；异步 `asyncio` |
| Web 后端 | FastAPI + uvicorn（127.0.0.1，单用户） |
| 数据校验 | Pydantic v2 |
| LLM SDK | `anthropic`（原生）+ `openai`（兼容端点） |
| 存储 | SQLite（`sqlite3`/SQLAlchemy 二选一，v1 倾向轻量）+ 文件 |
| 沙箱 | Docker（Python `docker` SDK）；候选 Java 服务 |
| 可观测 | Langfuse（自托管） |
| 密钥 | `keyring`（OS keychain） |
| 桌面壳 | pywebview + Web 前端 |
| 打包 | PyInstaller / Briefcase → `.app`/`.dmg`（不转 TS） |
| 前端 | 待 M2 定（React vs 更轻方案，PRD §12 待定） |

### 8.3 Git 协作规范（2 人）
- **分支**：`main` 受保护（不直推）；功能走 `feat/<模块>-<简述>`、修复 `fix/<…>`；**PR + 对方 review 后合并**。
- **提交信息**：`类型(范围): 说明`（`feat/fix/docs/refactor/test/chore`）。
- **进库 / 不进库**：
  - ✅ 进库：`core/ server/ cli/ tests/ docs/ agents/ skills/ pyproject.toml AGENTS.md`。
  - ❌ gitignore：`cc-resourcecode/`（已忽略）、`.env`/密钥、`__pycache__/`、`.venv/`、`*.db`、`<session>/transcript.jsonl`、构建产物。
  - ⚠️ **参考资料**（如同事新加的 `docs/CLAUDE-FABLE-5.md` 模型系统提示词）：建议挪到 `references/` 并 **gitignore**（尤其 repo 若公开）——它是学习材料、非项目设计。**待团队确认**。
- **AGENTS.md = 给 agent 的"地图"**（`research.md §C-26`）：约 100 行，写 build/test 命令、目录约定、`docs/` 是 source of truth；别写成千页手册。Agent Y 自己跑编码任务时也读它。
- **接口契约改动**：改 §4 任一接口 → PR 标题带 `[contract]` 并 @ 对方，合并前必须双方确认。

### 8.4 分工建议（M1，**待定稿确认**）
> PRD §13：分工待定。下面是基于"接口已隔离"的一个可并行方案：
- **开发者 A（偏 core）**：`types` + `loop` + `engine` + `providers/anthropic`。
- **开发者 B（偏工具/基础设施）**：`tools`(协议+4 内置) + `sandbox/docker` + `obs/console` + `cli`。
- 两人先**一起把 §4 接口冻结**，再各写各的，用 mock 对接；`harness`/`memory`/`eval` M1 先放最小桩。
- Java（同事擅长）落点在 **M5 沙箱执行器服务**或待办后端——M1 不阻塞。

---

## 9. M1 详细拆解（可直接转 GitHub Issues）

> **M1 验收（PRD）**：CLI 里给个编码任务，Docker 沙箱里把失败测试改绿；写操作会先确认。**dogfood 标准**：作者能用它修一个真实小 bug。

| # | Issue | 范围 / 验收 | 依赖 | 建议负责 |
|---|---|---|---|---|
| 1 | **定义核心数据类型** | `core/types.py`：§3 全部类型 + 单测序列化 | — | A |
| 2 | **冻结接口契约** | 把 §4.2/4.3/4.4 写成 `base.py` Protocol + docstring；双人 review | 1 | A+B |
| 3 | **Anthropic Provider** | `providers/anthropic.py`：流式解析成 `StreamEvent`；tool_use 块结束才 parse；usage 回填 | 1,2 | A |
| 4 | **agent_loop** | `core/loop.py`：act-observe；**以 tool_use 块判停**；max_turns；abort；错误即消息 | 1,2,3 | A |
| 5 | **Tool 协议 + 注册表 + 并发分桶** | `tools/base.py`+`registry.py`：两段式校验、权限门、`asyncio.gather` 分桶 | 1,2 | B |
| 6 | **内置工具 ×4** | `bash/read_file/write_file/edit_file`，含 `is_read_only` 标志与 `validate_input` | 5 | B |
| 7 | **Docker 沙箱** | `sandbox/docker.py`：起受限容器(断网/限资源)、exec/读写文件 | 2 | B |
| 8 | **最小审批** | `harness/approval.py`：只读自动放行 / 写操作 CLI 确认（READ_ONLY/ASK 两档先行） | 5 | B |
| 9 | **Console Tracer** | `obs/tracer.py`+`console.py`：run/llm/tool span 打印 | 1 | B |
| 10 | **SessionEngine（最小）** | `engine.py`：组 system+context、调 loop、串起 provider/tools/tracer、写 transcript.jsonl | 3,4,5,9 | A |
| 11 | **CLI 入口** | `cli/main.py`：`agenty run "<任务>"`，直连 Engine（不经 HTTP） | 10 | A/B |
| 12 | **编码任务样例 + 冒烟测试** | 1 个"修复失败测试"样例 workspace + e2e 测试（M1 验收用例） | 7,11 | A+B |
| 13 | **AGENTS.md + README + 跑通文档** | 开发/运行说明、AGENTS.md 地图 | — | 任一 |

**M1 不做**（明确推迟）：GUI、Langfuse、OpenAI 兼容、向量记忆、完整压缩（先全保留 + 超长截断兜底）、子 agent 并行、自进化。

---

## 10. 待解决 / 后续细化（design 演进时补）
- 前端框架选型（M2）、SQLite 用裸 `sqlite3` 还是 SQLAlchemy（v1 倾向裸/轻）。
- trace span → eval 样本的具体 schema 映射（`research.md §④-4`）。
- prompt 注入 / 上下文中毒防护的具体规则（`research.md §④-5`）。
- 自进化"失败聚类归因"的具体实现（规则 vs LLM 反思的边界）。
- M2+ 各模块详细设计（本文 M2–M6 仅粗线条）。

---

> 本文是 M1 开工蓝图；M2 起每进一个里程碑，回填对应模块的详细设计。接口契约（§4）是两人协作的冻结面，改动须双方确认。
