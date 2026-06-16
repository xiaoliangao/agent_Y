# 通用个人 Agent Runtime — 落地计划（编码 + 日常事务双能力，Hermes 式）

> 状态：选题已定 · 环境/仓库已就绪（Phase 0 完成）· 下一站 **M1**。
> 仓库：`git@github.com:xiaoliangao/agent_Y.git`（工作目录 `/home/ubuntu/coding_agent`）。

> ⚠️ **技术栈/形态以 [`docs/PRD.md`](./PRD.md) 为准**：经产品讨论已确定 **Python 运行时 + 多 Provider 原生适配(BYOK) + macOS 桌面 GUI(pywebview + Web 前端, 首屏 chat+trace)**，取代本文下方早期的 TypeScript 假设。本文的**架构思想、里程碑、Eval 自进化闭环设计仍然有效**，但**语言相关的代码骨架（§2 技术栈、§3.2 接口示例、§5 第一周清单）将按 Python 同步重写**（待办）。

---

## 1. Context（为什么是这个选题）

你曾在 "coding agent" 和 "个人 Agent 助手（Marvis / WorkBuddy / Hermes 那类多 Agent + 可观测 + Eval 自进化闭环）" 之间纠结。

澄清后的目标：**个人、边做边学、可放进简历，但更要功能做扎实——像 Hermes Agent 一样既能帮你处理日常事务（日程/邮件/文档等），也能完成编码任务。**

**首要学习目标（贯穿全程的指北针）：通过这个项目「学会做项目（工程化：结构/测试/可观测/迭代）」+「掌握 Agent 相关（吃透 agent loop、工具/技能体系、多 Agent 编排、Eval 自进化）」。** 因此实现取舍优先「能学到本质 + 工程上立得住」，而非最快出 Demo——**关键的 agent loop 要能看懂、能改、能讲清楚。**

核心判断：**"coding vs 助手" 是伪命题。** 「多 Agent 编排 + 可观测 + Eval 自进化」是与场景**解耦的底座**；编码和日常事务都是底座上的"应用"。所以：

> 做一个**通用个人 Agent Runtime**，把三件套做成核心内核；**编码与日常事务都是一线能力，但分阶段交付**——先用编码场景把 Eval 自进化闭环跑出**可量化效果**（编码任务评分客观，最能证明"自进化"、最有简历说服力），随后把日常事务能力作为**可插拔场景插件**逐个接入做扎实，**不重选题**。

预期产出：一个能演示"任务执行 → 全链路可观测 → 自动 Eval → 据失败自动改进 → 回归验证提升"完整闭环的个人 Agent，附可量化提升曲线；编码与日常事务两类能力均可实际使用。

---

## 2. 技术栈（已定 + 理由）

模型 id / 价格已与 `claude-api` skill 核对（current）：

| 用途 | 模型 | model id | 价格（输入/输出 /1M） | 上下文 |
|---|---|---|---|---|
| 主力（orchestrator、难任务） | Claude Opus 4.8 | `claude-opus-4-8` | $5 / $25 | 1M |
| 跑量 / 子任务 | Claude Sonnet 4.6 | `claude-sonnet-4-6` | $3 / $15 | 1M |
| 廉价子任务 / 分类 | Claude Haiku 4.5 | `claude-haiku-4-5` | $1 / $5 | 200K |

**调用约定**（Opus 4.8）：`thinking: {type: "adaptive"}` + `output_config: {effort: "high"}`（可选 `xhigh`）；**不要**用 `budget_tokens` / `temperature` / `top_p`（4.8 会 400）；`max_tokens` 大时走 streaming。

| 层 | 选型 | 理由 |
|---|---|---|
| 语言 | **TypeScript** 为主；编码沙箱评分脚本用 Python（pytest 等天然） | 与 `cc-resourcecode` 参考一致、便于边读边懂；后续 TUI/桌面端也顺 |
| LLM 调用 | **`@anthropic-ai/sdk`（基座 SDK）** | 直接 `messages.create` + tool use，最贴近 agent loop 本质 |
| **agent loop** | **自己手写**（基座 SDK 之上的薄封装） | ⭐ 学习目标的核心。loop = 上下文拼装 → `messages.create(tools)` → 检测 `tool_use` → 执行工具 → 回灌 `tool_result` → 看 `stop_reason` 决定是否继续。对照 `cc-resourcecode/query.ts` 边写边懂 |
| 编排 | 先手写 orchestrator + subagent（fork/spawn 子上下文） | 多 Agent 也要吃透本质，参考 `coordinator/` 与 `tools/AgentTool/` |
| 可观测 | **Langfuse**（开源自托管） | 一套搞定 tracing + dataset + eval，简历展示好（M2 起接入） |
| Eval | 自建 harness；编码任务在 **Docker 沙箱** 跑测试评分；事务类用 LLM-judge + 规则 | 编码客观、事务类半客观 |
| 自进化 | 失败聚类 → prompt/工具/few-shot 记忆改进 → 回归（DSPy 式思路，v1 规则化 + LLM 反思即可） | 据失败自动改、仅当提升才保留 |

> **`@anthropic-ai/claude-agent-sdk` 的定位**：它是更高层的"全家桶"——**自带 agent loop、内置工具（Read/Write/Bash/Glob/Grep/WebSearch…）、subagents、hooks、MCP、权限/会话**。但它**把 loop 藏起来了**，直接用它会学不到本质。所以：**v1 不用它来跑核心 loop**；等你手写的 loop 跑通后，把它当作"production 级参考实现"来**读源码 + 对照**，看它怎么处理 hooks/会话/权限/上下文压缩，再决定哪些能力借鉴进自己的 runtime。
>
> 备选（M1 动手时再定可调）：编排想吃透多 Agent 可换 LangGraph；可观测可换 OpenTelemetry + 自建 viewer。

---

## 3. 架构（四层 + 多场景应用）

```
┌─────────────────────────────────────────────────────────┐
│  应用层（可插拔场景插件，均为一线能力）                    │
│   - 编码场景 CodingAgent     ← 先做，点亮 Eval 闭环        │
│   - 日常事务 ProductivityAgent（日程/邮件/文档/检索）      │
└─────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────┐
│  Eval + 自进化闭环层                                       │
│   数据集 → 自动评分 → 失败分析 → 改进候选 → 回归对比       │
└─────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────┐
│  可观测层（Tracing）：每步 LLM/工具/决策/token/延迟        │
└─────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────┐
│  Agent Runtime 核心：Orchestrator + SubAgents +           │
│   统一 Tool/Skill 插件接口 + 记忆/会话                     │
└─────────────────────────────────────────────────────────┘
```

**关键设计**：场景只通过"注册一组 Tool + 一个 Eval 数据集 + 可选记忆策略"接入；Runtime / 可观测 / Eval 闭环对场景无感知。**加新能力 = 写插件，不动内核。**

### 3.1 目录脚手架（建议）

```
agent_Y/
  src/
    core/
      loop.ts        # 手写 agent loop（M1 核心）
      llm.ts         # @anthropic-ai/sdk 薄封装（注入 tracer）
      tool.ts        # Tool 接口 + 注册表 + findTool 分发
      types.ts       # Message / ToolUse / ToolResult / RunResult
    tools/           # 内置工具：bash / readFile / writeFile / editFile …
    obs/
      tracer.ts      # span/event 抽象（M1 console 版 → M2 Langfuse）
    sandbox/
      docker.ts      # 在容器内跑命令/测试，返回 exit code + 输出
    eval/
      harness.ts     # 跑全集、出通过率（M3）
      improve.ts     # 失败分析 → 改进候选 → 回归（M4）
      tasks/         # 编码任务集（每个含 workspace + 测试 + 评分）
    scenarios/
      coding/        # 编码场景：注册工具 + 提供 eval 数据集
      productivity/  # 日常事务（M5）
  tests/
  docs/plan.md       # 本文件
```

### 3.2 核心抽象（学习级，参考 `cc-resourcecode` 精简而来）

**Tool 接口**（对照 `cc-resourcecode/Tool.ts` 的 `Tool<>` / `buildTool` / `findToolByName`，砍到最小可用）：

```ts
// src/core/tool.ts
import { z, ZodType } from "zod";

export interface ToolContext {
  cwd: string;
  tracer: Tracer;
  // 后续可加：权限检查、abort signal、parentMessage 等
}

export interface ToolResult {
  content: string;       // 回灌给模型的文本
  isError?: boolean;
}

export interface Tool<I = unknown> {
  name: string;
  description: string;            // 写清"何时用"，不只是"做什么"
  inputSchema: ZodType<I>;        // → JSON schema 喂给 API；同时做运行时校验
  readOnly?: boolean;             // 并行安全提示（grep/read 可并行）
  execute(input: I, ctx: ToolContext): Promise<ToolResult>;
}

export function findTool(tools: Tool[], name: string) {
  return tools.find(t => t.name === name);
}
```

**Agent loop**（对照 `cc-resourcecode/query.ts` 的 `queryLoop()`）：

```ts
// src/core/loop.ts —— 伪代码骨架，M1 落地
export async function runAgent(opts: {
  system: string;
  messages: Message[];
  tools: Tool[];
  model: string;              // "claude-opus-4-8"
  tracer: Tracer;
  maxSteps?: number;
}): Promise<RunResult> {
  const span = opts.tracer.startRun();
  for (let step = 0; step < (opts.maxSteps ?? 30); step++) {
    const res = await callModel({          // src/core/llm.ts
      model: opts.model,
      system: opts.system,
      messages: opts.messages,
      tools: toToolDefs(opts.tools),       // {name, description, input_schema}
      thinking: { type: "adaptive" },
      output_config: { effort: "high" },
    });                                     // tracer 记录 token/延迟/决策
    opts.messages.push({ role: "assistant", content: res.content });

    if (res.stop_reason !== "tool_use") {  // end_turn → 收尾
      span.end("completed");
      return { messages: opts.messages, final: res };
    }
    const toolResults = await Promise.all(  // readOnly 工具可并行
      res.content.filter(b => b.type === "tool_use").map(async b => {
        const tool = findTool(opts.tools, b.name);
        const out = await tool.execute(b.input, ctx);  // tracer 记录工具 span
        return { type: "tool_result", tool_use_id: b.id, content: out.content, is_error: out.isError };
      })
    );
    opts.messages.push({ role: "user", content: toolResults });
  }
  span.end("max_steps");
  return { messages: opts.messages, final: null };
}
```

**Tracer 事件**（M1 先 console/JSONL，M2 换 Langfuse，接口不变）：

```ts
export interface Tracer {
  startRun(): Span;
  // 每个 Span 记录：type(llm|tool|decision) / 输入输出 / token / 延迟 / 父子关系
}
```

---

## 4. 里程碑（带验收标准）

> 每个里程碑都以 `cc-resourcecode` 对应模块为研习参照，先读懂再自己写最小版。

**M1 — Runtime 最小闭环** ⭐当前
内容：`core/`（loop + llm + tool + types）+ 2~3 个内置工具（bash / readFile / writeFile/editFile）+ `sandbox/docker.ts` + 一个 console 版 tracer。
验收：给 agent 一个"让某个失败测试通过"的编码任务，它能在 Docker 沙箱里读文件 → 改文件 → 跑测试 → 测试转绿。
研习参照：`query.ts`、`Tool.ts`、`tools.ts`。

**M2 — 可观测**
内容：`obs/tracer.ts` 接 Langfuse（自托管），完整 trace 一次执行树（决策 + LLM/工具 + token/延迟）。
验收：在 Langfuse UI 回看一次任务的完整调用树，每步 token/延迟可见。

**M3 — Eval harness（编码）**
内容：`eval/harness.ts` + `eval/tasks/` 放 5~20 个编码任务（每个 = 一个最小 workspace + 测试 + 评分脚本），一键跑全集出**基线通过率**。
验收：`npm run eval` 跑完整任务集，输出 pass@1 等指标，结果落 Langfuse dataset。

**M4 — 自进化闭环（核心卖点）**
内容：`eval/improve.ts`——据失败聚类自动生成改进候选（改 prompt / 加 few-shot 记忆 / 调工具描述）→ 重跑 → **仅当通过率提升才保留**；产出**可量化提升曲线** + 可解释改进记录。
验收：跑一轮改进，对比前后指标确认提升、可解释、可回滚。

**M5 — 日常事务能力（第二场景插件）**
内容：`scenarios/productivity/` 接 1~3 个工具（日程/邮件/文档/检索）+ 其 Eval（LLM-judge + 规则）。
验收：接入事务能力后，**未改动 runtime/observability/eval 内核**即跑通——证明换场景只写插件。

**M6 — 桌面/交互外壳（可选）**
Ink TUI 或简单 Web/桌面端，统一驱动两类能力。研习参照：`cc-resourcecode/ink/`。

---

## 5. 第一周动手清单（把 M1 推起来）

1. `npm init` + TypeScript + Zod + `@anthropic-ai/sdk`；配 `.env`（`ANTHROPIC_API_KEY`，已在 `.gitignore`）。
2. 写 `core/types.ts` + `core/llm.ts`（最小 `callModel` 封装，先不接 tracer）。
3. 写 `core/tool.ts` + 一个 `tools/bash.ts`，跑通"模型调用一次 bash 工具并拿到结果"。
4. 写 `core/loop.ts`，跑通多步循环（让它连续用几个工具完成一个小任务）。
5. 写 `sandbox/docker.ts`，造第一个编码任务（一个含失败测试的小目录）。
6. 串起来：`runAgent` 在沙箱里把测试改绿 → M1 达成。
7. 读 `cc-resourcecode/query.ts` 对照自己的 loop，记下差异（写进 `docs/` 学习笔记）。

> 动手前先读 `claude-api` skill 的 tool-use 部分确认 `messages.create` 的 tool 调用形状（manual agentic loop 模式）。

---

## 6. 关键决策记录

- **底座优先，场景分阶段**：简历真正值钱的是底座（多 Agent + 可观测 + Eval 自进化），编码与事务都做、但不在同一阶段堆。
- **编码先点亮闭环**：编码 Eval 客观，是把"自进化"做出可量化效果的最佳起点。
- **场景插件化**：统一 Tool 接口 + 独立 Eval 数据集接入，加能力不重选题。
- **loop 自写、Agent SDK 作参考**：核心 loop 用基座 `@anthropic-ai/sdk` 手写（学本质）；`@anthropic-ai/claude-agent-sdk` 当 production 参考读源码，不用它跑核心 loop。
- **cc-resourcecode 仅作参考**：gitignore，不进 `agent_Y`；按模块边读边自写最小版。

---

## 7. 验证方式（端到端）

1. **环境**：`ssh -T git@github.com` 成功、`git push` 到 `agent_Y` 成功。（已完成）
2. **功能闭环**：跑一个编码任务，agent 在 Docker 沙箱内完成并跑通测试。
3. **可观测**：Langfuse 中回看该次执行完整 trace。
4. **Eval**：一键跑编码任务集出基线通过率。
5. **自进化（核心验收）**：跑一轮改进，对比前后指标，确认提升、可解释、可回滚。
6. **第二场景（M5）**：接入事务能力后，确认未改动 runtime/observability/eval 内核。

---

## 8. 待确认 / 可调整项

- v1 编码任务集来源：**自建小任务集（最快，推荐 M3 起步）** vs 接 SWE-bench-lite 子集（更有说服力但更重，可作 M4 后扩展）。
- ~~语言主线 TS vs Python~~ → **已定：TS（基座 SDK + 手写 loop）**，编码评分脚本用 Python。编排 SDK vs LangGraph、可观测 Langfuse vs OTel —— M1/M2 动手时定。
- 是否需要 M6 桌面外壳，以及形态（TUI / Web / Electron）。
