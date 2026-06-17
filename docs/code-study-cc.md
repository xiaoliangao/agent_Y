# Claude Code 源码走读笔记 —— 给 Agent Y 的借鉴

> **这份文档是什么**：`cc-resourcecode/` 是 Claude Code 的 TypeScript 源码（仅作学习参考、已 gitignore）。本笔记是对其中 6 个核心子系统（agent loop / 上下文压缩 / 工具系统 / 子 Agent 编排 / 技能 / 记忆）的一次系统化走读，由 5 路并行深读合成。所有 `file:line` 锚点相对 `cc-resourcecode/`，均可核对。
>
> **怎么用**：① 作为 `docs/design.md`（技术设计文档）的实现依据；② 作为 0 基础学习者理解"一个真实生产级 Agent 到底怎么搭"的教材；③ 第 8 节专门记录了它**修正 `docs/research.md` v1 设想**的地方，必读。
>
> **一句话心法**：Claude Code 有 ~80 万行，但真正的"agent 本质"只占很小一块，其余全是 Anthropic 服务端耦合、终端 UI（Ink/React）、灰度实验开关（feature flag）、生产级边角恢复。**本笔记的核心价值就是帮你把那一小块本质从噪音里剥出来**——剥出来的部分，Python 几乎可以 1:1 复刻。

---

## 0. TL;DR —— 5 条会影响设计的结论

1. **Loop 的前进条件是"模型有没有返回 tool_use 块"，不是看 `stop_reason`。** 源码注释明说 `stop_reason==='tool_use'` 不可靠（`query.ts:554-556`）。这条直接抄进 Agent Y 的 while 循环。

2. **"完整压缩"本身就是一次普通的 LLM 调用**——fork 一个单轮、禁工具的请求让模型写摘要。任何端点（含 OpenAI 兼容）都能做。Claude 服务端真正独有、我们缺的只有"工具结果清理（microcompact）"，而它的客户端 fallback（time-based，把旧工具结果换成占位串）恰好给了可直接抄的蓝本。**整套上下文管理是纯客户端代码，Python 可 1:1 复刻**（第 2 节给了带默认数值的配方）。

3. **Claude Code 生产环境的记忆系统里没有向量数据库、没有 α·相关性+β·时近性+γ·重要性 的加权公式。** 它用的是「markdown 文件 + frontmatter 描述 + 让一个小模型挑出 ≤5 条 + 把时近性写成『47 天前保存』这样的人话喂给大模型」。**这修正了我们 research.md 的 v1 配方**（详见第 8 节）——可以砍掉 SQLite 向量索引和三权重调参，把省下的复杂度投到"写入端该存/不该存的过滤规则"上。

4. **子 Agent 的命门是"只回传最后一条 assistant 文本"**（`finalizeAgentTool`，`tools/AgentTool/agentToolUtils.ts:276`）。子 Agent 在自己独立的消息历史里疯狂调工具，父 Agent 只收到一段最终报告 + 一行用量——这就是"上下文不被子 Agent 噪音污染"的全部秘密。

5. **工具的执行结果是一个纯数据对象（DTO），"给模型看的序列化"和"给人看的渲染"是它的两个独立纯函数。** 这个解耦与 UI 框架无关，是工具系统能长期演进的根本。配合"两段式校验（形状 + 语义）+ 错误即消息（不抛异常）+ fail-closed 默认"，构成 Agent Y 工具抽象的核心。

---

## 1. 核心 Agent Loop

### 机制本质
真正的 loop 只有约 80 行有效逻辑（其余 1500 行是恢复/压缩/UI 噪音）。骨架（`query.ts:241` `queryLoop`，`while(true)` 在 `query.ts:307`）：

```
state = { messages, turn_count, ... }          # 可变状态，单点重组 query.ts:268
while True:
    1. 历史预处理：取压缩边界后的消息 + 注入 context        # query.ts:365-451
    2. 流式调模型                                          # query.ts:659  for await callModel(...)
         边收边 yield；把 assistant 消息里的 tool_use 抽出
         needsFollowUp = (有没有 tool_use 块)               # query.ts:554-558,834
    3. if not needsFollowUp:                               # 模型不再要工具 = 收尾
         跑 stop hooks / 检查 token 预算 → return "completed"  # query.ts:1062,1357
    4. else: 执行工具                                       # query.ts:1382 runTools
         yield 工具结果；收进 toolResults
    5. 停止检查：turn 超 maxTurns → return "max_turns"      # query.ts:1705
    6. 下一轮 state = [历史 + assistant 消息 + 工具结果]      # query.ts:1716（单点重组）
```

**关键设计**：
- **唯一前进信号 = 有没有 tool_use 块**（不看 stop_reason）。`query.ts:554-558`。
- **不是递归，是迭代 + 显式 state 重组**：每轮末把 `[历史+助手+工具结果]` 拼成新 messages 塞回 `state`，所有 `continue` 站点只写 `state = {...}` 一处。
- **全栈 async generator**：`query` / `queryLoop` / `callModel` / `runTools` 都是 `async function*`，用 `yield*` 串联；`return {reason}` 是流的终结值（与 yield 出的中间消息区分）。这让上层既能边流式消费、又能拿到最终停止原因。

### 流式解析（`services/api/claude.ts:1940` 的事件 switch）
按 Anthropic SSE 事件累积，**accumulate-then-finalize** 模式：
- `content_block_start`：`tool_use` 的 `input` 初始化为**空字符串**（入参是分片 JSON）。
- `content_block_delta`：`input_json_delta` → `input += partial_json`（`claude.ts:2111`，**块结束才 `JSON.parse`**）；`text_delta`/`thinking_delta` 各自累加。
- `message_delta`：流末尾才带来真实 `usage` 和 `stop_reason`，回填到最后一条消息（`claude.ts:2242`）。

### 停止条件
- 自然结束（无 tool_use）→ stop hooks / token 预算后 `completed`。
- `max_turns`、`abort` 信号（流式中/工具前/工具内三处查，中断时要**补全缺失的 tool_result**，否则 API 400）。
- token 预算（`query/tokenBudget.ts`）：注意这是"agent 该不该继续干活"的预算，**与上下文窗口压缩无关**，别混。

### 两层职责分工（最该学的架构边界）
- **`query.ts` = 纯 loop 引擎**：输入 messages/system/tools/canUseTool，输出消息流 + 停止原因。**不碰持久化、不碰 UI、不构建 system prompt**。可单测、可换 provider。
- **`QueryEngine.ts` = 会话编排层**：构建 system prompt、组装 context、消费 query 的流、翻译成对外消息、写 transcript、累计用量。`interrupt()` 就是 `abortController.abort()`。

### Agent Y 借鉴（Python）
```python
while True:
    resp = call_model(messages, system, tools)          # 流式 generator
    messages.append({"role":"assistant","content":resp.content})
    tool_uses = [b for b in resp.content if b.type=="tool_use"]
    if not tool_uses:                                    # 等价 needsFollowUp==False
        return "completed"
    tool_results = run_tools(tool_uses)                  # 见第 3 节
    messages.append({"role":"user","content":tool_results})
    turn += 1
    if max_turns and turn > max_turns: return "max_turns"
```
- 用 Python `generator`（`yield` 中间消息、`return reason`）让 FastAPI 端能 SSE 流出——和 TS 的 async generator + 终结值一一对应。
- 每个 provider 写一个 adapter，把各自的流事件归一成"accumulate-then-finalize"结构。
- 用一个 `@dataclass State`，每轮末整体替换，而非散落改变量。abort 传一个 `asyncio.Event`，在三处查。
- **分两层**：`agent_loop()` 纯 generator（不碰 DB/HTTP）+ `SessionEngine`（持 messages、abort、选 provider、写库、翻译响应）。FastAPI handler 只调 SessionEngine。

### 该忽略
所有 `feature('XXX')` 编译期开关、三套压缩的失败恢复迷宫（prompt-too-long 二级恢复、max_output_tokens 重试、模型 fallback）、`stream_event` 原始事件透传、Ink 渲染、teammate/dream/skill-discovery 等业务 stop hooks、VCR 录制回放、`tengu_*` 遥测。

> 锚点：`query.ts`（219-339, 654-863, 1062-1357, 1380-1727）、`QueryEngine.ts`（184-336, 675-732）、`services/api/claude.ts:1940-2304`、`utils/api.ts:437-474`（context 分流）。

---

## 2. 上下文管理 / 压缩（compact）—— 对 BYOK 最关键

> 这是 Agent Y 必须自己实现的一块：Claude 原生有服务端压缩原语，但我们要支持的 OpenAI 兼容端点（GPT/DeepSeek/本地）没有。好消息：**完整压缩本就是纯客户端的**，真正缺的只有工具结果清理，且有可抄的客户端 fallback。

### 三个层级（阈值从低到高）
```
① microcompact（微压缩，便宜，清旧工具结果）       ← 每次 API 请求前检查
② full compact（完整压缩，贵，调 LLM 写摘要）       ← token 占满阈值时
③ reactive compact（兜底，API 返回 prompt_too_long）
```

### 触发：基于绝对 token 数（不是百分比）
- `effectiveContextWindow = 上下文窗口 − min(模型最大输出, 20_000)`（给摘要输出预留，`autoCompact.ts:33-49`）。
- `compact 触发点 = effectiveContextWindow − 13_000`（`AUTOCOMPACT_BUFFER_TOKENS`，`autoCompact.ts:62-91`）。对 200K 模型 ≈ 167K（约 83.5%），但**判定用绝对值**。
- 熔断：连续 3 次压缩失败就停（`MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES`，曾有 session 重试 3272 次的教训）。

### 完整压缩 = 一次普通 LLM 调用
`compact.ts:387` `compactConversation`：fork 一个 `maxTurns:1`、禁 thinking、只给 Read 工具的子请求，喂入"压缩边界后的全部消息 + 摘要请求"，让模型输出摘要 → 把摘要包成一条 user 消息，替换掉边界后的原始消息。**默认不保留原文**（保留最近 N 条是 session-memory-compact 路径的事，见下）。

### 摘要提示词的 9 段式（`services/compact/prompt.ts:61-143`，直接抄）
要求模型先在 `<analysis>` 里逐条过对话（事后正则剥掉省 token），再输出 `<summary>`，**强制覆盖**：① 用户所有请求与意图 ② 关键技术概念 ③ 文件与代码片段（带完整 snippet + 为何重要）④ 每个错误与修复 ⑤ 问题解决 ⑥ **所有用户消息**（理解意图漂移）⑦ 待办任务 ⑧ 当前正在做什么 ⑨ 下一步（必须对齐用户最近的显式请求 + 逐字引用防漂移）。
- 关键技巧：`maxTurns:1` 时禁工具（否则浪费唯一一轮）；`<analysis>` scratchpad 先想后写再剥掉；摘要末尾附"完整记录见 transcript 路径"做可回溯逃生舱。

### 工具结果清理（microcompact，我们要自己实现的那块）
`microCompact.ts`。白名单 `COMPACTABLE_TOOLS` = Read/Bash/Grep/Glob/WebSearch/WebFetch/Edit/Write（输出可重新获取的才清）。**可抄的 time-based 路径**（`microCompact.ts:446-530`）：保留最近 `keepRecent=5` 个，其余可压缩工具结果的 content 整个换成占位串 `'[Old tool result content cleared]'`。判断标准：① 工具名在白名单 ② 不在最近 N 个 ③ 还没被清过。
- 服务端常量当默认值：触发 `180_000`、清理后目标 `40_000`。

### token 估算（`utils/tokens.ts:226` `tokenCountWithEstimation`，聪明的混合法）
不每轮重算全部，而是"**锚点 + 增量估算**"：从尾部找最近一条带真实 API usage 的 assistant 消息（那一刻的精确大小），只对它之后的新消息做粗估再加上去。粗估规则：字符数/4（JSON 用 /2，图片固定 2000）；末尾 `*4/3` 保守高估。

### 保留策略（`sessionMemoryCompact.ts:324` `calculateMessagesToKeepIndex`，可直接抄）
- 从上次已总结处之后保留，往回扩展直到 **≥10_000 token 且 ≥5 条含文本消息**，硬上限 **40_000 token**。
- **切点绝不能切断 tool_use/tool_result 配对**，也不能把同 message.id 的 thinking 块切散——孤立的 tool_result 引用不存在的 tool_use 会 API 400。这是最容易踩的坑。

### Agent Y 实现配方（OpenAI 兼容端点，Python harness 层）
```
A. token 估算：锚点(信对端返回的 usage / 或 tiktoken) + 增量粗估(len/4，JSON /2，图 2000)，*4/3 保守
B. 阈值(绝对值)：EFFECTIVE = 窗口 − min(max_output, 20k)
   COMPACT_TRIGGER = EFFECTIVE − 13k；MICRO_TRIGGER ≈ EFFECTIVE*0.6
   每次调 API 前：≥COMPACT 做完整压缩；≥MICRO 先清工具结果；连续 3 次失败熔断
C. 工具结果清理：白名单 + KEEP_RECENT=5，其余 content 换占位串
D. 完整压缩：同模型发一次禁工具单轮请求，9 段式提示词，事后剥 <analysis>
E. 保留：最近 ≥10k token 且 ≥5 条文本，上限 40k，切点对齐工具配对
F. 重注入(别丢)：最近读过的 ≤5 个文件、当前 plan/被调 skill、项目记忆(MEMORY.md)、工具清单
G. 摘要附"完整记录见 transcript 路径"
```

### 该忽略
所有服务端原语（cache editing、`clear_tool_uses_20250919`、`clear_thinking`、prompt cache 共享/break 检测）、`/count_tokens` 端点与 Haiku 探针、GrowthBook 实验开关、多 forked-agent 共进程的递归守卫与模块级状态治理、`tokenBudget.ts`（那是工作量预算不是上下文压缩）。

> 锚点：`services/compact/`（`autoCompact.ts`、`compact.ts`、`microCompact.ts`、`prompt.ts`、`sessionMemoryCompact.ts`、`postCompactCleanup.ts`）、`utils/tokens.ts:226`、`services/tokenEstimation.ts`。

---

## 3. 工具系统

### Tool 接口契约（`Tool.ts:362`）
一个工具不是 class，是满足结构类型的对象，经 `buildTool({...})`（`Tool.ts:783`）用 `TOOL_DEFAULTS`（`Tool.ts:757`）补默认值。核心成员：

| 类别 | 成员 | 作用 |
|---|---|---|
| 身份 | `name` / `aliases?` / `description()` / `prompt()` / `isEnabled()` | 名字、给模型的一行描述、完整说明书 |
| Schema | `inputSchema`（**必填，Zod**）/ `validateInput?()` | 形状校验 / 语义校验 |
| 安全 | `checkPermissions()` / `isReadOnly()` / `isConcurrencySafe()` / `isDestructive?()` | 权限三态 + 并发/破坏性标志 |
| 执行 | `call()` → `Promise<ToolResult>` | 执行函数（非 generator，进度走 `onProgress` 回调） |
| 渲染 | `mapToolResultToToolResultBlockParam()`（给模型）/ `renderToolResultMessage?()`（给人） | **双重渲染** |

**fail-closed 默认**（`Tool.ts:757`）：未声明就当作"会写、不可并发、需问权限"。这是最该照搬的安全姿态。

### 两段式校验（`services/tools/toolExecution.ts:599`，错误即消息）
1. **结构校验**：`inputSchema.safeParse(input)`（`:615`）。失败 → 构造 `is_error:true` 的 tool_result：`<tool_use_error>InputValidationError: ...</tool_use_error>` 回灌给模型。注释直言"模型不擅长生成合法入参"，所以**错误必须可读、可自纠，绝不抛异常中断 loop**。
2. **语义校验**：`validateInput?()`（`:683`），做需要 I/O/上下文的检查（文件存在、deny-rule、"文件自上次读取后被改"），**故意把 I/O 推迟到权限通过之后**。失败同样回 `<tool_use_error>`。

> 口诀：**Zod 管"形状对不对"，validateInput 管"这次调用合不合法"，两者失败都是文本反馈不是异常。**

### 权限 + 并发
- `behavior ∈ {allow, deny, ask}`，`!= 'allow'` 就短路成 error。**只读工具默认放行、写工具默认 ask**。
- `isReadOnly` 同时驱动**并发分桶**（`toolOrchestration.ts:91` `partitionToolCalls`）：连续的并发安全工具合成一批并行跑（有界并发，默认上限 10），非安全工具各自串行。**并行批的 context 修改要先收集、整批跑完后再顺序应用**，别在并行中改共享状态——这条坑早抄早省事。

### 双重渲染（最该学的解耦）
`call` 返回**结构化 `data: Output`**（绝不是字符串/拼好的 prompt）。两条独立通道消费它：`mapToolResultToToolResultBlockParam`（序列化给模型，可加行号/system-reminder）vs `renderToolResultMessage`（给人看的 UI）。**模型 context 与 trace 显示从此互不污染。**

### 渐进披露 ToolSearch（工具多到撑爆 context 时才需要）
MCP 工具可能几百个。机制：模型 turn-1 只在 system-reminder 里看到工具**名字**（没有 schema 所以无法调用）→ 需要时调 `ToolSearchTool`（`select:Read,Edit` 或关键词）→ 返回 `tool_reference` block，API 把它展开成完整工具定义注入后续 context。仅当延迟工具 token 占比 >10% 才自动启用。**Agent Y v1 不需要**，留个 `should_defer: bool = False` 字段占位即可。

### Agent Y 借鉴（Python）
```python
class Tool(Protocol, Generic[TInput, TOutput]):
    name: str
    input_model: type[TInput]                 # Pydantic v2 = Zod；model_json_schema() 直接喂 API
    def is_read_only(self, inp) -> bool: ...           # 默认 False
    def is_concurrency_safe(self, inp) -> bool: ...    # 默认 = is_read_only
    async def validate_input(self, inp, ctx) -> ValidationResult: ...
    async def check_permissions(self, inp, ctx) -> PermissionResult: ...  # allow/deny/ask
    async def call(self, inp, ctx, on_progress) -> ToolResult[TOutput]: ...
    def to_model_result(self, data, tool_use_id) -> dict: ...   # 给模型
    def render_for_ui(self, data) -> dict: ...                  # 给前端 trace
```
- **Pydantic 当 Zod**：`model_json_schema()` 直接喂 Anthropic `tools[].input_schema`；`ValidationError` → 格式化成 `<tool_use_error>` 回灌。
- 基类提供 fail-closed 默认；`call` 返回 Pydantic Output（纯数据），序列化与渲染是它的两个纯函数。
- `is_read_only` 驱动 `asyncio.gather` 并发分桶 + `asyncio.Semaphore(10)` 上限。
- BYOK 多 provider：tool_result 协议统一成 Anthropic 格式，OpenAI 的 `tool_calls`/`tool` role 在 adapter 层转换。

### 该忽略
所有 React/Ink 渲染方法、transcript 搜索基础设施、prompt 缓存对齐排序、海量 feature flag、`ToolUseContext` 的 ~50 个字段（v1 只需 `abort_signal`/`read_file_state`/`messages`/`on_progress`/`cwd`）、MCP beta-header、PreToolUse/PostToolUse hook observability。

> 锚点：`Tool.ts`（321-336, 362-695, 757-791）、`services/tools/toolExecution.ts`（599-733, 1207-1292）、`services/tools/toolOrchestration.ts`（91-152）、`tools/FileReadTool/`、`tools.ts`（193-366）。

---

## 4. 子 Agent / 编排

### 核心范式
**子 Agent = 一次隔离的、跑在自己 message loop 里的 query，只把最后一条 assistant 文本回传给父。** 父子靠"prompt 进 / 摘要出"做信息隔离。

### 生命周期
1. **spawn**：父用 `Agent` 工具发起，入参 `{description, prompt, subagent_type, model?, run_in_background?}`（`AgentTool.tsx:82`）。`prompt` 是**唯一信息入口**。
2. **隔离执行**（`runAgent.ts:248`）：子 Agent 有**独立 agentId、独立 messages 数组（普通子 Agent 起始只有 prompt，看不到父历史）、独立 ToolUseContext、独立 file-state、独立 sidechain transcript（写盘独立文件不污染父）**。工具池按子 Agent 自己的定义**独立重建**，不继承父的临时授权。
3. **回传摘要（命门）**：`finalizeAgentTool`（`agentToolUtils.ts:276`）只取"最后一条有文本的 assistant 消息"的文本，**不含任何中间 tool_use/tool_result**，作为一个 tool_result block 回到父上下文。父只看到"最终报告 + 一行用量"。system prompt 对父明说："子 Agent 完成后只返回一条消息给你。"

### 隔离 vs fork
- **普通子 Agent（带 `subagent_type`）= 全新开始，完全隔离**。要把它当"刚进门、没看过对话的同事"来 brief。
- **fork（省略 `subagent_type`，实验特性）= 继承父的完整历史 + system prompt 原文**。用途：中间工具输出不值得留在父上下文时，父把活儿 fork 出去保持自己干净。fork 共享 prompt cache 所以不能换模型。

### Agent 定义格式（markdown + frontmatter，`loadAgentsDir.ts:541`）
```markdown
---
name: code-reviewer            # 必填 → agentType
description: Use this agent...  # 必填 → 给父看的"何时用我"
tools: Read, Grep, Bash        # 白名单；省略=全部；'*'=全部
disallowedTools: Write, Edit
model: sonnet                  # opus/haiku/inherit
maxTurns: 50
skills: commit, verify
isolation: worktree            # 独立 git worktree
---
<markdown 正文 = 这个 agent 的 system prompt>
```
来源优先级合并：built-in < plugin < user < project < flag < policy，同名后者覆盖。

### Task 抽象（`Task.ts:45`）
把"一次后台可管理的执行单元"统一封装。`TaskStateBase` = `id / type / status(pending/running/completed/failed/killed) / description / outputFile(结果落盘可 tail) / ...`。`local_agent`、`remote_agent`、`local_bash`、甚至**主会话本身**都是 Task 的不同 type。停止统一走 `kill(taskId)`。

### 编排模型（`coordinator/coordinatorMode.ts`，实验）
"单写者 + 并行 fan-out"：协调者自己不写代码，只拆任务、派 worker、综合结果。并发规则落到文件层：只读任务随便并行，**写任务一次只能一个 worker 动同一组文件**。worker 结果以 `<task-notification>` 异步回流。协调者最重要职责是 **synthesize**——读懂 worker 报告后写出带具体文件/行号的下一步 spec，绝不能甩"based on your findings, fix it"。

### Agent Y 借鉴（即使 v1 单线程，把接口留成这个形状）
```python
async def run_agent(agent_def, prompt, parent_context_messages=None) -> AgentResult:
    # parent_context_messages=None → 隔离(默认)；传入 → fork。一个参数切两种语义
    # 跑自己独立的 messages list 和 loop；回传只取最后一条 assistant 文本
```
- **必抄原则**：子 Agent 独立 message 历史 + 只回传最终文本摘要。即使 v1 同步跑也照此接口，将来加并行/远程不用重构。
- 父工具池放一个 `spawn_agent` 工具，返回值 = `AgentResult.content`（一个 tool_result block）。
- Agent 定义用 `agents/*.md`（frontmatter + 正文当 system prompt），`python-frontmatter` 解析。
- 留钩子（v1 不实现）：极简 `Task`（`id/status/result`）存进 `dict[task_id, Task]`，将来 FastAPI `GET /tasks/{id}` 查状态；`kill()` 用 `asyncio.CancelledError`。

### 该忽略
整套 prompt cache 对齐、fork 实验本身（用 `parent_context_messages` 参数预留语义即可）、多进程/teammate/swarm、远程 CCR Agent、git worktree 隔离、agent memory 持久化、per-agent MCP/hooks/skills 预加载、handoff 安全审查。

> 锚点：`tools/AgentTool/`（`AgentTool.tsx:82,239,1340`、`runAgent.ts:248`、`agentToolUtils.ts:276`、`forkSubagent.ts`、`loadAgentsDir.ts:541`）、`coordinator/coordinatorMode.ts:116`、`Task.ts:45,72`。

---

## 5. Skills 技能

### 定义格式
一个 skill = **一个目录 + `SKILL.md`**（目录名即 skill 名，`loadSkillsDir.ts:424-452`）。头部 YAML frontmatter，正文 markdown。核心字段：`name` / `description` / `when_to_use`（渐进披露关键）/ `allowed-tools` / `model` / `disable-model-invocation` / `context: fork`。可带同目录脚本/资源（正文里用 `${CLAUDE_SKILL_DIR}/script.py` 引用）。

### 渐进披露（"常用事务做成 skill 但不撑爆上下文"的全部秘密）
1. **列表只放 frontmatter，不放正文**：渲染成 `- name: description - whenToUse` 一行一条，整个列表**只占 1% 上下文窗口**（默认 8000 字符上限，单条描述 ≤250 字符，`SkillTool/prompt.ts:20-29`）。
2. **token 估算只算 frontmatter**（`loadSkillsDir.ts:100`）。
3. **正文在 invoke 时才展开**：模型调 `Skill` 工具 → 这时才读取并注入完整 markdown 正文。

> 一句话：**列表 = 全部 skill 的(name + 一句话)；正文 = 命中时按需加载。不需要任何向量检索，模型看描述自己挑。**

### 来源
managed(企业) / user(`~/.claude/skills`) / project(向上遍历) / bundled(内置编译进二进制)，按真实路径去重 first-wins。

### Agent Y 借鉴（几乎 1:1 照搬）
- 目录约定 `skills/<name>/SKILL.md`，`python-frontmatter` 解析。
- 渐进披露照抄：注册时只拼 `- {name}: {description}` 放进 system prompt（设字符预算）；提供 `Skill(name, args)` 工具，命中才读正文注入。
- 来源分层：内置 / 用户级 / 项目级。**2 人团队场景，项目级 skill 提交进 git 就天然共享，不需要专门同步系统**。

### 该忽略
团队同步、MCP/remote/plugin skill、Windows/符号链接极端处理、prompt cache 细节、`tengu_*` 灰度。

> 锚点：`tools/SkillTool/prompt.ts:20-29,70-171`、`skills/loadSkillsDir.ts:100-105,185-265,407-480,638-804`、`skills/bundledSkills.ts`。

---

## 6. Memory 记忆 —— 修正 research.md v1 配方

> **最大的认知更新**：Claude Code 生产环境的记忆系统**比我们设想的轻得多**——没有 SQLite，没有向量索引，没有数值加权公式。它用「纯文件系统 + frontmatter + 小模型挑选」。

### 存储格式
- 位置：`~/.claude/projects/<git-root>/memory/`（**按 git 仓库根**分目录）。
- **一条记忆 = 一个 `.md` 文件 + frontmatter**：`name / description / type`，正文是内容。
- **`MEMORY.md` 是索引不是记忆**（`memdir.ts:34`）：**始终常驻 system prompt**，每条一行指针 `- [Title](file.md) — 一句话钩子`，硬上限 200 行/25KB。
- **写入两步**：① 写 topic 文件 ② 在 MEMORY.md 加一行指针。按**主题语义**组织（不按时间），先查重再写。
- **四种类型**（闭集，`memoryTypes.ts:14-19`）：`user`（角色/目标/偏好）、`feedback`（工作方式指导，带 **Why**）、`project`（进行中工作/决策的"为什么"，相对日期转绝对）、`reference`（外部系统指针）。**明确排除"能从项目状态推导的东西"**——代码模式、架构、文件路径、git 历史、调试 fix recipe 一律不存（grep/git 当场能查，存了会过时变误导）。

### 召回机制：LLM 挑选，不是向量也不是加权
1. **扫描 frontmatter**（每文件只读前 30 行），按 **mtime 倒序**取前 200 个候选。
2. **让一个小模型（Sonnet）挑**：把候选格式化成 manifest（`[type] filename (timestamp): description`）+ 用户 query 发给小模型，JSON schema 强制返回选中文件名数组。
3. **"相关性"标准写在提示词里**：只选**确定**有用的（≤5 个），不确定就别选，可返回空。
4. **注入回对话**：选中文件读出来作为 `<system-reminder>` 注入，每条附时近性文本"Memory (saved 47 days ago)"。
5. **时近性的真实作用**（`memoryAge.ts`）：不是算分，而是**生成给模型看的人类可读陈述**——模型不擅长日期算术，原始 ISO 时间戳触发不了陈旧性推理，但"47 days ago"可以；>1 天的附"可能过时，断言前先核对"警告。

> **关键结论**：**没有 α·相关性+β·时近性+γ·重要性 的数值公式。** "加权"是把所有信号（type、时近、描述）作为文本喂给小模型用语言判断。重要性根本没显式建模——靠写入端的"什么该存/不该存"过滤。

### 自动沉淀（两套独立系统，别混）
- **(A) 长期记忆 `extractMemories`**（跨会话，沉淀进 memory 目录）：每个 loop 结束、模型给出无工具最终回复时由 stop hook 触发 → fork 一个受限子 agent（只看最近 N 条、**不准 grep/git 验证**、turn 上限 5、与主 agent 当轮互斥），按四类 taxonomy 写记忆文件，**强制先查重**。
- **(B) SessionMemory**（单会话工作笔记，**为压缩续接服务，不是跨会话记忆**）：固定模板（Current State / Task spec / Files / Errors / Learnings / Worklog），阈值驱动后台 fork agent 更新。**如果 Agent Y v1 还没做 auto-compact，这套可以先不做。**

### Agent Y 借鉴 —— 对照 research.md v1 逐条校准

| research.md v1 设想 | Claude Code 真实做法 | 给 Agent Y 的建议 |
|---|---|---|
| SQLite + 向量索引 | **没有**，纯文件 + frontmatter | **v1 可砍向量索引**。SQLite 顶多当 mtime/路径缓存 |
| α相关+β时近+γ重要 加权公式 | **没有公式**，小模型挑 ≤5 条 | **改成"LLM 挑选"**。手调三权重既难又脆 |
| 时近性 | mtime 倒序截断候选 + "N days ago"文本给模型 | 照搬，用文件 mtime，别自建时间戳字段 |
| 重要性 γ | **完全没建模** | **v1 直接砍**，精力投到写入端过滤规则 |
| MEMORY.md 索引 | ✅ 一致（常驻索引，非记忆本身） | 照搬两层结构 |
| 环境式反思/自动沉淀 | ✅ 有（fork + 强约束 + 便宜） | 照搬 fork+约束模式 |

**Memory 最小可行方案**：① `<project>/memory/<topic>.md`（frontmatter `name/description/type`）② `MEMORY.md` 常驻索引 ③ 召回：扫 frontmatter → 小模型选 ≤5 → 注入附"saved N days ago" ④ 沉淀：每轮结束 fork 受限子 agent 按 taxonomy 提炼并查重 ⑤ 直接采用四类 taxonomy（提示词都被 eval 反复打磨过，可借鉴）。

### 该忽略
团队记忆同步（TEAMMEM）、KAIROS 助手日志/dream 夜间蒸馏、GrowthBook 灰度、Windows/符号链接极端处理、MCP/remote/plugin skill 记忆、SessionMemory（v1 没做压缩前先不做）。

> 锚点：`memdir/findRelevantMemories.ts:18-141`、`memdir/memdir.ts:34-38,199-266`、`memdir/memoryTypes.ts:14-19,113-195,261-271`、`memdir/memoryAge.ts:6-42`、`services/extractMemories/extractMemories.ts:329-523`、`utils/attachments.ts:2196-2332`。

---

## 7. Agent Y v1 借鉴清单（汇总，可直接进 design.md）

**核心 loop**
- [ ] while 循环以"有没有 tool_use 块"为前进条件，不看 stop_reason
- [ ] 流式解析按 accumulate-then-finalize（tool 入参分片 JSON，块结束才 parse）
- [ ] 分两层：`agent_loop()` 纯 generator + `SessionEngine`（持状态/选 provider/写库/翻译）
- [ ] State 单点重组；abort 在"调模型前/工具前/工具内"三处查，中断补全缺失 tool_result

**工具系统**
- [ ] Tool 协议：Pydantic 当 schema（`model_json_schema()` 喂 API），fail-closed 默认
- [ ] 两段式校验（形状 safeParse + 语义 validate_input），错误即消息不抛异常
- [ ] 权限三态 allow/deny/ask；`is_read_only` 驱动并发分桶（gather + Semaphore(10)）
- [ ] `call` 返回纯数据 Output，序列化(给模型)与渲染(给 trace)是两个独立纯函数
- [ ] BYOK：tool_result 协议统一成 Anthropic 格式，OpenAI 在 adapter 层转换

**上下文管理（OpenAI 兼容端点必做）**
- [ ] token 估算：锚点(对端 usage / tiktoken) + 增量粗估(len/4，JSON /2，图 2000)，*4/3
- [ ] 阈值绝对值：COMPACT = (窗口 − min(max_out,20k)) − 13k；连 3 次失败熔断
- [ ] 工具结果清理：白名单 + KEEP_RECENT=5，旧的换占位串
- [ ] 完整压缩：禁工具单轮 LLM 调用 + 9 段式提示词 + 剥 `<analysis>`
- [ ] 保留：最近 ≥10k token 且 ≥5 条文本，上限 40k，切点对齐工具配对
- [ ] 压缩后重注入：最近文件/plan/skill/MEMORY.md/工具清单

**Skills**
- [ ] `skills/<name>/SKILL.md`（frontmatter `name/description/when_to_use` + 正文）
- [ ] 渐进披露：列表只放(name+一句话)设字符预算，命中才注入正文
- [ ] 来源分层（内置/用户/项目）；项目级 skill 进 git 即团队共享

**Memory**（按第 8 节修正后的方案）
- [ ] `<project>/memory/<topic>.md` + `MEMORY.md` 常驻索引（两层）
- [ ] 召回用 LLM 挑选（小模型选 ≤5 条），**不做向量库、不做 α/β/γ 公式**
- [ ] 时近性写成"saved N days ago"文本喂大模型，不进打分
- [ ] 自动沉淀：每轮结束 fork 受限子 agent，按四类 taxonomy 提炼并查重
- [ ] 重心放在"写入端该存/不该存的过滤规则" + 四类 taxonomy 提示词

**子 Agent**（v1 留接口不实现并行）
- [ ] `run_agent(agent_def, prompt, parent_context_messages=None)`：None=隔离，传入=fork
- [ ] 只回传最后一条 assistant 文本（命门）；Agent 定义用 `agents/*.md`

---

## 8. 对 docs/research.md 的修正与确认

走读后需要更新 research.md 的两处认知：

1. **【修正】Memory v1 配方**：research.md 原写"SQLite + 本地向量索引 + 加权召回 α·相关性+β·时近性+γ·重要性"。Claude Code 生产实践证明**不需要向量库、不需要加权公式**——用"frontmatter 描述 + 小模型挑 ≤5 条 + 时近性文本化"即可。**建议 Agent Y v1 据此简化**，把省下的复杂度投到写入端过滤规则和四类 taxonomy 提示词（那才是被 eval 反复打磨、真正决定记忆质量的地方）。向量检索作为"记忆条数很多之后的可选增强"后置。

2. **【确认】research.md 待补清单**：
   - 待补 #1（OpenAI 兼容端点如何在 harness 层自实现 compaction/clearing）→ **本笔记第 2 节已给出完整可落地配方**。
   - 待补 #3（cc-resourcecode query.ts 代码走读）→ **本笔记第 1 节已完成，并扩展到全部 6 个子系统**。
   - 待补 #6（tool search / 渐进披露实现）→ **第 3、5 节已覆盖**（工具渐进披露 + 技能渐进披露）。
   - 仍待补：#2 开源记忆库选型（mem0/Zep/Letta，但优先级因本笔记下降——CC 证明纯文件方案够用）、#4 Langfuse trace 反哺自进化 schema、#5 prompt 模板/注入防护。

---

## 附：关键文件锚点速查

| 子系统 | 必读文件（相对 `cc-resourcecode/`） |
|---|---|
| 核心 loop | `query.ts`、`QueryEngine.ts`、`services/api/claude.ts:1940`、`services/tools/toolOrchestration.ts`、`utils/generators.ts`（`all()` 有界并发）、`utils/api.ts:437`（context 分流） |
| 压缩 | `services/compact/{autoCompact,compact,microCompact,prompt,sessionMemoryCompact}.ts`、`utils/tokens.ts:226`、`services/tokenEstimation.ts` |
| 工具 | `Tool.ts`、`services/tools/{toolExecution,toolOrchestration}.ts`、`tools/FileReadTool/`、`tools.ts` |
| 子 Agent | `tools/AgentTool/{AgentTool.tsx,runAgent.ts,agentToolUtils.ts,forkSubagent.ts,loadAgentsDir.ts}`、`coordinator/coordinatorMode.ts`、`Task.ts` |
| Skills | `skills/loadSkillsDir.ts`、`tools/SkillTool/prompt.ts`、`skills/bundledSkills.ts` |
| Memory | `memdir/{findRelevantMemories,memdir,memoryTypes,memoryAge}.ts`、`services/extractMemories/`、`utils/attachments.ts:2196` |
