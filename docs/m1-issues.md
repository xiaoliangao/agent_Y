# M1 任务清单（→ GitHub Issues）

> 来源：`docs/design.md §9`。**M1 验收**：CLI 给一个编码任务，Docker 沙箱里把失败测试改绿、写操作先确认；dogfood = 作者能用它修一个真实小 bug。
>
> **怎么用**：① 手动——照下表在 GitHub 逐条新建 Issue；② 自动——装好 `gh`（`gh auth login`）后跑文末「批量创建脚本」。
>
> 标签建议：`M1` `area:core` / `area:tools` / `area:infra` / `good-first` 等。负责 A=作者（Agent 内核），B=同事（基础设施/工具），详见 `design.md §8.4`。

## 共同第一步（开工前）
**[M1] 冻结 §4 接口契约**（Issue #2）— 两人一起过一遍 `design.md §4` 的 5 组 Protocol（已在 `core/*/base.py` 落成桩），确认签名 → 合并。之后改契约走 `[contract]` PR + 双确认。

## 任务表

| # | 标题 | 负责 | 依赖 | 验收要点 |
|---|---|---|---|---|
| 1 | **定义核心数据类型** | A | — | `core/types.py` 全类型（已落）+ 单测序列化通过 |
| 2 | **冻结接口契约** | A+B | 1 | `core/*/base.py` Protocol 双人 review 通过、签名冻结 |
| 3 | **Anthropic Provider** | A | 1,2 | `providers/anthropic.py`：流式解析成 `StreamEvent`；tool_use 块结束才 parse；usage 回填 |
| 4 | **agent_loop** | A | 1,2,3 | `core/loop.py`：act-observe；**以 tool_use 块判停**；max_turns；abort；错误即消息 |
| 5 | **Tool 注册表 + 并发分桶** | B | 1,2 | `tools/registry.py`：两段式校验、权限门、`asyncio.gather` 分桶（只读并行/写串行）|
| 6 | **内置工具 ×4** | B | 5 | `bash/read_file/write_file/edit_file`，含 `is_read_only` 与 `validate_input`；`edit` 先读后写 |
| 7 | **Docker 沙箱** | B | 2 | `sandbox/docker.py`：起受限容器（断网/限 CPU/内存/时长）、exec/读写文件 |
| 8 | **最小审批** | B | 5 | `harness/approval.py` `gate()`：只读自动放行 / 写操作 CLI 确认（READ_ONLY/ASK 两档先行）|
| 9 | **Console Tracer** | B | 1 | `obs/tracer.py` ConsoleTracer：run/llm/tool span 打印（输入输出摘要/token/延迟）|
| 10 | **SessionEngine（最小）** | A | 3,4,5,9 | `engine.py`：组 system+context、调 loop、串 provider/tools/tracer、写 `transcript.jsonl` |
| 11 | **CLI 入口** | A/B | 10 | `cli/main.py`：`agenty run "<任务>"` 直连 Engine（不经 HTTP）|
| 12 | **编码样例 + 冒烟 e2e** | A+B | 7,11 | 1 个"修复失败测试"样例 workspace + e2e 测试（M1 验收用例）|
| 13 | **AGENTS.md + README + 跑通文档** | 任一 | — | 安装/运行说明（已起 `AGENTS.md`）|

**M1 不做**（明确推迟）：GUI、Langfuse、OpenAI 兼容、向量记忆、完整压缩（先全保留 + 超长截断兜底）、子 agent 并行、自进化、助手场景。

---

## 批量创建脚本（装了 `gh` 后运行）
```bash
# 前置：gh auth login；在仓库目录下运行
gh label create M1 --color FBCA04 -f 2>/dev/null || true
gh label create area:core -f 2>/dev/null || true
gh label create area:tools -f 2>/dev/null || true
gh label create area:infra -f 2>/dev/null || true

gh issue create -t "[M1] 定义核心数据类型 (core/types.py)" -l M1,area:core \
  -b "见 docs/design.md §3。types 已落骨架；补全 + 单测序列化。负责: A。验收: 全类型可序列化、测试通过。"
gh issue create -t "[M1] 冻结接口契约 (core/*/base.py)" -l M1,area:core \
  -b "见 docs/design.md §4。两人一起 review 5 组 Protocol 并冻结。负责: A+B。依赖: #1。"
gh issue create -t "[M1] Anthropic Provider" -l M1,area:core \
  -b "见 docs/design.md §4.2。流式解析成 StreamEvent；tool_use 块结束才 parse；usage 回填。负责: A。依赖: #1,#2。"
gh issue create -t "[M1] agent_loop" -l M1,area:core \
  -b "见 docs/design.md §1.2/§4。act-observe；以 tool_use 块判停；max_turns；abort；错误即消息。负责: A。依赖: #1,#2,#3。"
gh issue create -t "[M1] Tool 注册表 + 并发分桶" -l M1,area:tools \
  -b "见 docs/design.md §4.3。两段式校验、权限门、asyncio.gather 分桶。负责: B。依赖: #1,#2。"
gh issue create -t "[M1] 内置工具 ×4 (bash/read/write/edit)" -l M1,area:tools \
  -b "见 docs/design.md §4.3。含 is_read_only 与 validate_input；edit 先读后写。负责: B。依赖: #5。"
gh issue create -t "[M1] Docker 沙箱" -l M1,area:infra \
  -b "见 docs/design.md §4.4。受限容器(断网/限资源)、exec/读写文件。负责: B。依赖: #2。"
gh issue create -t "[M1] 最小审批 gate()" -l M1,area:infra \
  -b "见 docs/design.md §5.1。只读自动放行/写操作确认(READ_ONLY/ASK)。负责: B。依赖: #5。"
gh issue create -t "[M1] Console Tracer" -l M1,area:infra \
  -b "见 docs/design.md §6.1。run/llm/tool span 打印。负责: B。依赖: #1。"
gh issue create -t "[M1] SessionEngine (最小)" -l M1,area:core \
  -b "见 docs/design.md §0/§1.2。组 system+context、调 loop、串 provider/tools/tracer、写 transcript.jsonl。负责: A。依赖: #3,#4,#5,#9。"
gh issue create -t "[M1] CLI 入口 agenty run" -l M1,area:core \
  -b "见 docs/design.md §1.1。直连 Engine 不经 HTTP。负责: A/B。依赖: #10。"
gh issue create -t "[M1] 编码样例 workspace + 冒烟 e2e" -l M1,area:tools \
  -b "1 个修复失败测试样例 + e2e 测试(M1 验收用例)。负责: A+B。依赖: #7,#11。"
gh issue create -t "[M1] AGENTS.md + README + 跑通文档" -l M1 \
  -b "安装/运行说明。负责: 任一。"
```
