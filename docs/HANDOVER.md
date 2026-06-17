# Agent Y 交接文档（Handover）

> 给作者 + 同事（或未来的你）的接手说明。读完这一份 + `README.md`，就能独立继续开发，不依赖原协作过程。
> 日期：2026-06-17 · 对应分支 `main`。

---

## 0. 一句话现状
Agent Y 是「会编码、能自进化的个人桌面工作助手」。**内核三件套（可观测 trace / BYOK 多模型 / Eval 自进化）已用真模型（DeepSeek）跑通**：编码闭环、token 级流式、自进化提升曲线（真机实测 50%→100%）。**42 个测试全过**。六阶段：需求①、设计②已定稿，编码③做到 M1–M4。

## 1. 五分钟上手
```bash
# 环境：Python 3.12+，Docker（可选，用真沙箱时），Node 18+（前端）
pip install -e ".[dev]"            # 装核心 + 测试依赖
pytest -q                          # 应 42 passed
python scripts/demo_loop.py        # 离线看 agent loop 跑（无需 API/Docker）
```
接真模型（以 DeepSeek 为例，OpenAI 兼容）：
```bash
export DEEPSEEK_API_KEY=sk-...
python -m cli.main run "修复失败的测试" --workspace examples/fix_failing_test --yes \
  --provider openai --base-url https://api.deepseek.com --model deepseek-chat --api-key-env DEEPSEEK_API_KEY
python -m cli.main eval    --taskset evals/coding-v1   <同上 provider 参数>   # 出 pass@1
python -m cli.main improve --taskset evals/coding-hard --rounds 2 <provider>  # 自进化提升曲线
```
桌面（后端 + 前端）：见 `docs/dev-setup.md §5.5`（`uvicorn server.app:app` + `cd agent-y && npm run dev`）。
**所有运行细节、Docker、排错都在 `docs/dev-setup.md`。**

## 2. 文档地图（改动前先读对应文档）
| 文档 | 作用 |
|---|---|
| `README.md` | 项目入口 + 六阶段看板 + 文档索引 |
| `docs/PRD.md` (v1.0) | **需求**：目标/用户故事/功能/原型图/里程碑/MVP DoD/决策。功能范围以此为准 |
| `docs/design.md` (v1.0) | **系统设计**：架构、**§4 接口契约（冻结面）**、数据模型、§8 工程规范、§9 M1 拆解 |
| `docs/research.md` | 调研：memory/自进化/harness·loop·context engineering + OpenAI 侧 + 术语，带引用 |
| `docs/code-study-cc.md` | Claude Code 源码 6 子系统行级走读 + Agent Y 借鉴清单（很多实现照它来的） |
| `docs/dev-setup.md` | **开发/运行指南**：安装、测试、CLI、server、Docker、排错 |
| `docs/m1-issues.md` | M1 任务清单（13 项，可转 GitHub Issues）|
| `docs/plan.md` | 早期计划，**已被 PRD/design 取代**，仅历史参考 |
| `evals/README.md` | 任务集格式（含隐藏测试）说明 |

## 3. 代码地图（`core/` 是内核）
```
core/
  types.py            ✅ 全局类型(Message/ContentBlock/StreamEvent…) —— 共享"语言"
  loop.py             ✅ agent_loop：act-observe；以 tool_use 块判停；token 级 yield delta
  engine.py           ✅ SessionEngine：组 context、调 loop、写 transcript
  providers/
    base.py           ✅ LLMProvider 协议（契约，冻结面）
    anthropic.py      ✅ Claude 原生（流解析有单测；⚠️未用真 key 实测）
    openai_compat.py  ✅ OpenAI 兼容（DeepSeek/GPT/本地，已真机实测）
    mock.py           ✅ 测试用假 provider
  tools/
    base.py           ✅ Tool 协议 + BaseTool + ToolContext（契约）
    registry.py       ✅ 校验→权限→执行 + 并发分桶
    bash/read/write/edit.py  ✅ 4 个内置工具
  harness/
    approval.py       ✅ 审批分级 gate()（只读/问/自动/放开）
    context.py        ⬜ 桩：上下文压缩（配方见 code-study-cc.md §2，待实现）
    fs_access.py      ⬜ 桩：文件夹授权（设计见 design §5.2，M5）
  memory/
    store.py          ◻️ 只有 Memory + MemoryStore 协议；recall/reflect 是桩（待实现）
  obs/tracer.py       ✅ ConsoleTracer；langfuse.py ⬜ 桩
  eval/               ✅ types/taskset/harness(run_task,run_taskset)/improve(improve,evolve)
  sandbox/
    base.py           ✅ SandboxExecutor 协议
    local.py          ✅ 宿主执行器（开发/测试用）
    docker.py         ✅ Docker 沙箱（真机测过；⚠️exec timeout 未强制、网络默认全关）
  scheduler/          ⬜ 桩：待办/提醒/自动化（M5）
  scenarios/coding/   ✅ 编码场景 + 系统提示词；assistant/ ⬜ 空（M5）
core/store.py         ✅ SQLite 会话/消息持久化
server/app.py         ✅ FastAPI REST+SSE（create_app 工厂）
cli/main.py           ✅ agenty run/eval/improve
agent-y/              ✅ 前端(Vite/React)，接后端 SSE；tsc+build 过（未浏览器逐项验收）
evals/                ✅ coding-v1(简单) / coding-hard(隐藏测试，演示自进化)
tests/                ✅ 42 个测试
```
图例：✅ 已实现+测过 · ◻️ 部分(仅协议/桩) · ⬜ 桩待实现。

## 4. 关键设计决策与"为什么"（动手前务必懂）
1. **接口契约在 `design.md §4` + 各 `*/base.py` 的 Protocol，是冻结面**。改它 → PR 标题带 `[contract]` + 双确认。跨模块只认协议 + Pydantic 数据类。
2. **loop 以"本轮有无 tool_use 块"判停，不看 stop_reason**（code-study + OpenAI 双重佐证）。
3. **fail-closed**：工具默认会写/不可并发/需确认；**错误即消息**：工具/校验失败回灌 `is_error` 的 tool_result，不抛异常中断 loop。
4. **两层切分**：`agent_loop`(纯逻辑可单测) vs `SessionEngine`(编排/IO)。CLI/server 都只是 loop 的客户端。
5. **Provider 抽象**：loop 永不 import 具体 provider；加一家 = 写一个 adapter（把各家流归一成 `StreamEvent`）。
6. **token 级流式**：loop 透传 provider delta；server `assistant` 事件不产帧（文本已逐字流过）、仅用于持久化。
7. **memory v1 不做向量库/不做 α·β·γ 加权**（code-study 校准）：markdown 文件 + 小模型挑选 + 写入端过滤。**当前仅协议，未实现**。
8. **自进化**：编码测试当客观真值；据失败学经验 → 留出验证/重跑 → **只升不降才保留**；`evolve` 多轮出曲线（in-sample 爬山，严格留出在单轮 `improve`）。
9. **交付形态**：全程 Python，最终 pywebview + PyInstaller/Briefcase 打包 `.app`，**不转 TS**（前端是 Web/后端 Python，经本地 HTTP 通信）。

## 5. 已知限制 / 待办（按优先级）
- ⬜ **memory 落地**：`recall`(小模型挑)/`reflect`(fork 受限子 agent) 仅桩，需实现（设计见 code-study §6）。
- ⬜ **上下文压缩** `harness/context.py`：长会话会撑爆 token，需实现（配方 code-study §2：阈值/工具结果清理/9 段式摘要）。
- ⬜ **M5 个人助手**：scheduler(待办/提醒/自动化)、scenarios/assistant(文件问答/办公文档/检索)、fs_access(文件夹授权) 全是桩。接口/数据模型已在 design 定好。
- ⬜ **Langfuse**：`obs/langfuse.py` 桩；trace 目前只 Console + 存 SQLite。
- ⚠️ **AnthropicProvider 未用真 Claude key 实测**；thinking+signature 回传留到后续（现默认关 thinking）。
- ⚠️ **DockerSandbox**：`exec` 超时未强制 kill；容器默认全程断网（`exec(network=)` 未透传）→ 容器内 `pip install` 装不了依赖（需依赖的编码任务先用 `--sandbox local` 或自定义镜像）。
- ⚠️ **token 流式**目前是"provider 给多少块就推多少"；前端用 `streamingIdRef` 累积进同一气泡。
- ⚠️ **前端**：tsc/build 过，但未逐项浏览器验收——按效果驱动迭代。
- ⚠️ **自进化曲线**真要好看需更多/更难任务（`evals/coding-hard` 是起点）。

## 6. 安全 / 协作注意事项
- 🔑 **密钥只走环境变量，绝不写进文件/日志/trace**（PRD F8.1，已贯彻；`git grep` 确认仓库历史无 key）。
- 🔑 **务必轮换那个 DeepSeek key**：`sk-8000…`（已在协作对话里出现过 → 视为已暴露），到 DeepSeek 控制台重置。
- `cc-resourcecode/`（Claude Code 源码，学习参考）、`references/`、`*.db`、`.agenty/`(运行时数据) 已 gitignore。
- `docs/CLAUDE-FABLE-5.md`（同事推的模型系统提示词）建议挪 `references/` 并 gitignore，尤其 repo 若公开——**待团队确认**。
- Git：`main` 走 PR + review；分支 `feat/<模块>-<简述>`；提交 `类型(范围): 说明`。
- 分工提案见 `design.md §8.4`（A=Agent 内核/编排/前端；B=工具/沙箱/server/scheduler/Java 落点），按同事技能微调。

## 7. 推荐的下一步（任挑）
1. **打包 `.app`**（PyInstaller/Briefcase + pywebview 套前端）——出能双击的成品。
2. **M5 个人助手**——把 scheduler/assistant 场景/办公文档 skill 从桩做实（接口已定）。
3. **memory + 上下文压缩**——让它"懂你"且能长会话（两块当前是桩）。
4. **Langfuse + 自进化看板**——trace/提升曲线落库可视。
5. **M1 收尾**——Docker 超时/网络放行、Anthropic 真 key 实测。

> 验证习惯：改完跑 `pytest -q`；接真模型用 DeepSeek 冒烟；接口改动走 `[contract]` PR。祝开发顺利。
