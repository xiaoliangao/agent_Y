# 选题与落地计划：通用个人 Agent（编码 + 日常事务双能力，Hermes 式）

## Context（为什么是这个选题）

你在"coding agent"和"个人 Agent 助手（Marvis / WorkBuddy / Hermes 那类多 Agent + 可观测 + Eval 自进化闭环）"之间纠结。

澄清后的目标：**个人、边做边学、可放进简历，但更要功能做扎实——像 Hermes Agent 一样既能帮你处理日常事务（日程/邮件/文档等），也能完成编码任务。** 技术上你真正想吃透的是「多 Agent 编排 + 可观测 + Eval 自进化闭环」这套工程内核。

**首要学习目标（贯穿全程的指北针）：通过这个项目「学会做项目（工程化：结构/测试/可观测/迭代）」+「掌握 Agent 相关（吃透 agent loop、工具/技能体系、多 Agent 编排、Eval 自进化）」。** 因此实现取舍优先考虑「能学到本质 + 工程上立得住」，而非最快出 Demo——关键的 agent loop 要能看懂、能改、能讲清楚。

核心判断：**"coding vs 助手"是伪命题。** 这三件套是与场景**解耦的底座**；编码和日常事务都是底座上的"应用"。因此选题定为：

> 做一个**通用个人 Agent Runtime**，把"多 Agent 编排 + 可观测 + Eval 自进化闭环"做成核心内核；**编码与日常事务都作为一线能力，但分阶段交付**——先用编码场景把 Eval 自进化闭环跑出**可量化效果**（编码任务评分客观，最能证明"自进化"且最有简历说服力），随后把日常事务能力作为**可插拔场景插件**逐个接入做扎实，**不重选题**。

环境现状（已勘查）：
- 工作目录定为 `/home/ubuntu/coding_agent`，关联远程 `git@github.com:xiaoliangao/agent_Y.git`（当前为**空仓库**）。
- 目录内已有 `cc-resourcecode/`（35MB / 1902 文件）= **Claude Code 的 TS 内部源码**，作为 agent loop / 工具体系 / 编排 / 技能机制的**参考素材**，**不纳入版本控制**（gitignore）。
- 本机**无 SSH 私钥**、无 git 身份、无 `gh`。认证方式已选定：**生成新 SSH 密钥**。

预期产出：一个能演示"任务执行 → 全链路可观测 → 自动 Eval → 据失败自动改进 → 回归验证提升"完整闭环的个人 Agent，附可量化提升曲线；编码与日常事务两类能力均可实际使用。

---

## Phase 0 — 环境与仓库初始化（让 Ultraplan 能跑 + 接上 agent_Y）

1. **生成 SSH 密钥**：`ssh-keygen -t ed25519 -C "eangyang0504@gmail.com" -f ~/.ssh/id_ed25519 -N ""`，然后**打印公钥**给你 → 你粘贴到 GitHub → Settings → SSH and GPG keys。
2. **配置 git 身份**：`git config --global user.name xiaoliangao`、`git config --global user.email eangyang0504@gmail.com`。
3. **初始化仓库**：在 `/home/ubuntu/coding_agent` 执行 `git init`，默认分支 `main`。
4. **`.gitignore`**：忽略 `cc-resourcecode/`、`node_modules/`、`__pycache__/`、`.env`、`dist/`、Docker 临时产物等。
5. **首个 commit**：脚手架 + README + .gitignore。
6. **关联远程并推送**：`git remote add origin git@github.com:xiaoliangao/agent_Y.git` → `ssh -T git@github.com` 验证 → `git push -u origin main`。
7. **重跑 Ultraplan**：此时已是 git 仓库，可成功启动云端精化。

> 阻塞点：第 1 步公钥需要你手动加到 GitHub，加完告诉我，我再继续 6/7。

---

## 架构（四层 + 多场景应用）

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

**关键设计**：场景只通过"注册一组 Tool + 一个 Eval 数据集 + 可选记忆策略"接入；Runtime / 可观测 / Eval 闭环对场景无感知。加新能力 = 写插件。可直接参考 `cc-resourcecode` 里 `Tool.ts` / `tools.ts` / `query.ts` / `coordinator` / `skills` 的抽象方式。

---

## 推荐技术栈

| 层 | 选型 | 理由 |
|---|---|---|
| 语言/编排 | **TypeScript + Claude Agent SDK 为主线，但 agent loop 自己写薄封装、不完全藏进 SDK**；编码沙箱评分脚本用 Python | 与学习目标对齐：薄封装能吃透 loop 本质（上下文拼装→LLM→工具调用→结果回灌→终止判断），又不必从零造拖慢工程进度；TS 与 `cc-resourcecode/query.ts`（真实 agent loop）一致、便于边读边懂，后续做 TUI/桌面端也顺 |
| LLM | **Claude（Opus 4.8 主力 / Sonnet 4.6 跑量 / Haiku 4.5 廉价子任务）** | 默认用最新 Claude；动手前先读 `claude-api` skill 确认 model id 与价格 |
| 编排 | **Claude Agent SDK**（subagents / tools / hooks 现成），核心 loop 薄封装 | 既学 agent loop 本质，又不必从零造 |
| 可观测 | **Langfuse（开源自托管）** | 一套搞定 tracing + dataset + eval，简历展示好 |
| Eval | 自建 harness；编码任务在 **Docker 沙箱** 跑测试评分；事务类用 LLM-judge + 规则 | 编码客观、事务类半客观 |
| 自进化 | 失败聚类 → prompt/工具/few-shot 记忆改进 → 回归（参考 DSPy 思路） | v1 规则化 + LLM 反思即可 |

> 备选：编排层若想吃透多 Agent 可换 LangGraph；可观测可换 OpenTelemetry + 自建 viewer。M1 动手时再定可调。

---

## 里程碑

**M1 — Runtime 最小闭环**：orchestrator + 1 subagent + Tool 插件接口，能在编码沙箱完成"让某测试通过"。
**M2 — 可观测**：接 Langfuse，完整 trace 一次任务执行树（决策 + LLM/工具 + token/延迟）。
**M3 — Eval harness（编码）**：5~20 个编码任务 + 沙箱自动评分，一键跑全集出通过率。
**M4 — 自进化闭环（核心卖点）**：据失败自动生成改进候选 → 重跑 → 仅当提升才保留；产出**可量化提升曲线** + 可解释改进记录。
**M5 — 日常事务能力（第二场景插件）**：接入日程/邮件/文档等 1~3 个工具 + 其 Eval（LLM-judge）；证明换场景只写插件、不改内核。
**M6 — 桌面/交互外壳（可选）**：Ink TUI 或简单 Web/桌面端，统一驱动两类能力。

---

## 关键决策记录

- **底座优先，场景分阶段**：简历真正值钱的是底座（多 Agent + 可观测 + Eval 自进化），编码与事务都做、但不在同一阶段堆。
- **编码先点亮闭环**：编码 Eval 客观，是把"自进化"做出可量化效果的最佳起点。
- **场景插件化**：统一 Tool 接口 + 独立 Eval 数据集接入，加能力不重选题。
- **cc-resourcecode 仅作参考**：gitignore，不进 `agent_Y`。

---

## 验证方式（端到端）

1. **环境**：`ssh -T git@github.com` 成功、`git push` 到 `agent_Y` 成功、Ultraplan 能启动云端会话。
2. **功能闭环**：跑一个编码任务，agent 在 Docker 沙箱内完成并跑通测试。
3. **可观测**：Langfuse 中回看该次执行完整 trace。
4. **Eval**：一键跑编码任务集出基线通过率。
5. **自进化（核心验收）**：跑一轮改进，对比前后指标，确认提升、可解释、可回滚。
6. **第二场景（M5）**：接入事务能力后，确认未改动 runtime/observability/eval 内核。

---

## 待确认 / 可调整项

- v1 编码任务集来源：自建小任务集（最快）vs 接 SWE-bench-lite 子集（更有说服力但更重）。
- ~~语言主线 TS vs Python~~ → **已定：TS + Claude Agent SDK，loop 自写薄封装**（见技术栈表，对齐学习目标）。编排 SDK vs LangGraph、可观测 Langfuse vs OTel —— M1 动手时定。
- 是否需要 M6 桌面外壳，以及形态（TUI / Web / Electron）。
