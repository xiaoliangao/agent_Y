# 实现前技术调研报告 — Agent Y

| 字段 | 值 |
|---|---|
| 版本 | v1（合并两轮深度调研） |
| 日期 | 2026-06-16 |
| 方法 | 两轮 deep-research：多角度并行检索 → 抓取一手来源 → 每条结论 3 票对抗式核对（2/3 反驳才淘汰）→ 带引用合成 |
| 覆盖 | A：Agent Memory + 自进化（深）；B：Harness / Loop / Context engineering（深）+ runtime landscape（轻） |
| 用途 | 喂给 `docs/design.md`（技术设计文档）；区分"工业级做法"与"小团队 v1 最小可信版" |
| 关联 | [PRD](./PRD.md) · [plan](./plan.md) |

> **给 0 基础读者的术语小抄**
> - **agent loop**：让模型反复"想→调用工具→看结果→再想"的循环，直到任务完成。
> - **ground truth（真值）**：每一步真实跑出来的结果（如测试通过/报错），不是模型自己猜的进度。
> - **context（上下文）**：每次请求塞给模型的全部内容（系统指令+工具+历史+数据）。窗口有限。
> - **context engineering**：管理"这次该放哪些 token 进上下文"的工程，比只写好提示词（prompt engineering）范围大。
> - **compaction（压缩）**：把很长的对话总结成短摘要再继续，腾出窗口。
> - **tool-result clearing（工具结果裁剪）**：把旧的工具输出删掉换成占位说明，不重新调模型、所以不花推理钱。
> - **RAG / 向量检索**：把文本转成向量存起来，按"语义相近"召回——记忆系统的主流实现。
> - **reflection（反思/记忆巩固）**：让模型把一堆原始记录提炼成更高层的"经验/洞见"。

---

## TL;DR（一页结论）

1. **业界共识已从"调模型/调 prompt"转向"做 harness + context engineering"**：模型能力之外，**脚手架（工具集、loop、上下文管理、验证回路）决定 agent 的实际上限**。这正是 Agent Y 的内核价值，也佐证了"**手写 loop、不藏进高层 SDK、用最简单方案按需加复杂度**"的定位（Anthropic 明确这么建议）。
2. **Memory 必须是独立的一层，不能靠大上下文窗口糊弄**——长上下文 ≠ 记忆。v1（据 `code-study-cc.md` 实践校准）用 **markdown 文件 + frontmatter 描述 + 小模型挑 ≤5 条召回 + 环境式反思**，把"向量索引 + α/β/γ 加权"降为后置增强；重心放在"写入端该存/不该存"的过滤。
3. **自进化 v1 别玄学**：编码场景用 Docker 测试当客观真值 → 失败归因 → 生成改进候选（改 prompt / 加 few-shot 记忆 / 调工具描述）→ **留出验证集回归，只升不降才保留、可解释可回滚** → 出 pass@1 提升曲线。DSPy/搜索/RL 留到反思遇瓶颈再上。
4. **多 Agent 先别急**：v1 单线程 loop 最稳（Cognition）。要上多 agent，2026 收敛做法是**单一写者 + 隔离子 agent 只做"情报/分析"并回传 1–2k 摘要**（Anthropic），别让多个 agent 并发写。
5. **本地优先 / BYOK 的现实**：Claude 原生有 compaction / tool-result clearing / memory 三个 server 端原语可直接用；但 **OpenAI 兼容端点没有等价 server 原语，这些裁剪/压缩要在我们 harness 层自己实现**——这是个明确的工程待办。

---

## ① 业界全景（带辨析 + 引用）

### A. Agent Memory 系统

**1. 已收敛出统一的"三轴分类法"——可直接当 memory 模块的设计骨架**〔高置信，3-0〕
- **时间尺度**：工作记忆（当前上下文内）/ 情景 episodic（发生过的事）/ 语义 semantic（事实知识）/ 过程 procedural（做事套路）。
- **存储形态**：上下文文本 / 向量索引 / 结构化（SQL·KV·知识图谱）/ 可执行库（代码、工具定义、计划模板）。
- **控制策略**：启发式规则 / 提示式自管理（把记忆操作做成工具给 agent 调）/ 学习式。
- 外加一轴 **agent-centric vs user-centric**——后者就是"个性化/懂你"。
- 来源：arXiv:2603.07670《Memory for Autonomous LLM Agents》(2026-03)；arXiv:2602.06052《Rethinking Memory…》(2026-02，综述 218 篇)。⚠️ 均为很新的非同行评审预印本，当"业界怎么分类"的描述用恰当，别当铁律。

**2. 存储形态选型谱**〔高置信，3-0〕
- 向量索引（RAG/ANN over embeddings，用 HNSW/IVF；外部记忆的主流实现）；线性/文件（FIFO 流，最直接、人类可读、需裁剪）；结构化（关系表/SQL + 知识图谱）；分层多存储 + 元记忆管理器按模块路由。
- 来源：arXiv:2602.06052；arXiv:2605.06716《From Storage to Experience》。

**3. 召回用"加权多项"，不是纯相似度**〔高置信，3-0，源为原始论文〕
- `score = α·relevance(向量余弦) + β·recency(指数衰减) + γ·importance(LLM 打分)`；先各自归一化到 [0,1]。
- 鼻祖 Generative Agents（Stanford）实现中三系数均 = 1，recency 衰减因子 0.995，importance 用 LLM 评 1–10。
- 来源：arXiv:2304.03442（UIST'23）；综述 arXiv:2605.06716 §4.1。**简单、可解释、面试讲得清。**

**4. 反思 / 记忆巩固**〔高置信，3-0〕
- Generative Agents：重要性累计超阈值（实现中 150，约每天 2–3 次）触发 → 从最近 100 条记忆生成问题 → 检索相关记忆 → 综合洞见并**引用证据条目**。
- 综述把反思分三类：内省式（自评）/ **环境式（外部信号作锚，降幻觉）** / 协作式（多角色共识）；Reflexion 为代表。
- 来源：arXiv:2304.03442；arXiv:2605.06716 §4.2。**编码场景建议用环境式：拿测试失败信号当锚。**

**5. MemGPT/Letta：超越固定窗口的工程范式**〔高置信，3-0〕
- OS 启发的虚拟上下文管理：在"快内存（上下文）↔ 慢内存（外部存储）"间搬数据，制造"更大上下文"的表象；用中断管理控制流；支持跨多会话"记住/反思/演化"。
- 来源：arXiv:2310.08560（2023 奠基经典）。

**6. 2024–2026 新进展（超越扁平向量库）**〔高置信，3-0〕
- **A-MEM**（Zettelkasten 风格）：写入时由 LLM 生成含描述/关键词/标签的结构化笔记，动态链接成知识网络，且**新记忆会触发对相关旧记忆的更新**（持续演化）。来源：arXiv:2502.12110，repo `agiresearch/a-mem`（Python）。
- **H-MEM**（分层记忆）：按语义抽象度分层，记忆向量内嵌指向下层的索引，检索时**逐层路由**而非全量相似度计算（记忆量大时更快）。来源：arXiv:2507.22925（EACL 2026）。

**7. 关键工程结论：长上下文 ≠ 记忆**〔中置信，2-1，方向可信〕
- 即便窗口拉到 200k，在"需要选择性检索"的任务上，长上下文模型仍**持续逊于专用记忆系统**；机制由"Lost in the Middle"（arXiv:2307.03172，U 形注意力衰减）等支撑。
- ⚠️ 被驳回的配套量化数字（某 80%→45%）证据不足，**本报告不引任何具体百分比**，只取方向性结论：**Agent Y 必须建独立记忆层。**

### B. 自进化 / 自我改进

**8. 已有成体系综述，提供现成框架与术语**〔高置信，3-0（综述层面）〕
- **进化什么**：模型 / **记忆** / 工具 / 架构（记忆是显式可进化对象，直连我们的记忆子系统）。
- **统一反馈回路**：System Inputs / Agent System / Environment / **Optimiser** 四组件。
- 综述明确**把编码列为最适合客观度量的评测域**。
- 来源：arXiv:2507.21046《A Survey of Self-Evolving Agents》(repo `CharlesQ9/Self-Evolving-Agents`)；arXiv:2508.07407。

**9. 按"改造代价"分层选优化器**〔中置信，框架推论〕
- 轻量 Optimiser = **规则 + LLM 反思**（Reflexion 式）：失败归因 → 改 prompt / 加 few-shot / 调工具描述 → 留出验证集回归 → 只升不降才保留。
- 重型 Optimiser = DSPy（prompt/程序自动优化）/ 搜索式自动设计（ADAS）/ RL —— **只在简单反思遇瓶颈时才上**。
- ⚠️ Reflexion(arXiv:2303.11366)、Self-Refine(arXiv:2303.17651)、DSPy、ADAS、Gödel Agent 等**本轮只在综述层面确认存在**，未逐篇 3-0 逐字核验；落地建议为框架级推论。

### C. Harness / Loop / Context engineering（B 轮，25 条全 3-0 确认）

**10. 三个概念的边界**〔高置信，3-0，Anthropic 一手定义〕
- **context engineering** = 在整个推理过程中策划/维护最优 token 集合（系统指令+工具+MCP+外部数据+历史），范围 > 只管指令写法的 prompt engineering。
- **loop engineering** = 设计上面那个反复"act-observe"的循环本身。
- **harness engineering** = 设计 agent 周围的全部脚手架（工具、loop、上下文管理、验证、沙箱）。
- 来源：Anthropic《Effective context engineering for AI agents》(2025)。

**11. 为什么 harness 决定上限：注意力预算 + context rot**〔高置信，3-0，多源〕
- LLM 有有限"注意力预算"，token 越多召回精度越低（"context rot"）。Chroma 实测 18 个前沿模型证实"输入越长性能越降"。
- ⚠️ "源于 n² 注意力"是 Anthropic 措辞，只是因素之一（还有训练分布/位置编码）；现象稳健、机制别单一归因。
- 来源：Anthropic 同上；Chroma《Context Rot》。

**12. M1 loop 的核心结构：act-observe + ground truth**〔高置信，3-0〕
- 每步从环境拿真值（工具结果/代码执行）评估进度，必要时回到人类判断。**编码场景完美契合：Docker 跑测试 = ground truth。**
- 来源：Anthropic《Building effective agents》(2024)。

**13. 停止条件 / 防死循环**〔高置信，3-0〕
- 除"任务完成"外，必须有显式停止条件（**最大迭代数 / 预算**）防 runaway。来源：同上。

**14. 少脚手架之争——直接支撑"手写 loop"**〔高置信，3-0〕
- Anthropic 明确：**先找最简单方案、按需才加复杂度；直接调 LLM API（很多模式几行代码）**；框架"会掩盖底层 prompt 与响应"。
- bitter-lesson 视角（browser-use 等）：模型变强后该砍脚手架——但这是**长期争论**，当下"做 harness"仍是主流。
- 来源：Anthropic《Building effective agents》。

**15. workflow vs agent**〔高置信，3-0〕
- workflow = 预定义代码路径编排 LLM+工具；agent = LLM 动态自主决定流程。**Agent Y 的"手写 loop + 多 Agent"其实是两者混合。** 来源：同上。

**16. context engineering 落地三件套**〔高置信，3-0〕
- **JIT + 渐进披露**：不预载全部，只存轻量标识（文件路径/查询），运行时用工具按需拉。⚠️ Anthropic 实推**混合**（少量预载如 CLAUDE.md + 按需检索），不是纯 JIT。
- **compaction 调参法**：先**最大化召回**（抓全相关信息）再**迭代提精度**（删冗余）。
- **子 agent 隔离**：子 agent 可烧几万 token 深挖，**只回传 1,000–2,000 token 摘要**给主 agent。
- 来源：Anthropic《Effective context engineering》。

**17. 长任务编码 harness 范式**〔高置信，3-0〕
- **两段式**：initializer agent 首次搭环境；coding agent 每会话做增量并为下次留清晰 artifacts。
- **跨会话状态**：外部 progress 文件（`claude-progress.txt`/`PROGRESS.md`）+ git 历史持久化，重启先读它们恢复状态（对应 cc-resourcecode 的 `memdir/`）。
- **compaction 单独不够**：即便 Opus 4.5 在 loop 里跨多窗口、只给高层 prompt 也建不出生产级 web app，需额外脚手架。⚠️ 厂商博客、"生产级"未量化。
- **self-verify 回路**：harness 必须对抗模型"没测就标完成"的倾向——要求它**自测通过才标 passing**。Agent Y 的"Docker 跑测试评分"正是这一回路。
- 来源：Anthropic《Effective harnesses for long-running agents》(2025) + 官方 repo `anthropics/cwc-long-running-agents`。

**18. 多 Agent 的活跃争论（别当定论）**〔部分 2-1〕
- **Cognition《Don't build multi-agents》(2025-06)**：多 agent 脆弱，决策分散、context 难充分共享 → 倾向**单线程线性 agent**。两条原则：①共享 context + 完整 trace（非单条消息）；②行动携带隐式决策，冲突 → 坏结果。
- **2026-04 软化**：多 agent **在"单一写者 + 额外 agent 只贡献情报而非并发行动"时**效果最好；并行写者 swarm 没见有意义采用。可行分层 = **manager-child（map-reduce-and-manage）**，但"比预期需要更多 context engineering"。
- Anthropic 同期则在 read-heavy 场景用 orchestrator+隔离子 agent 成功。
- 来源：cognition.ai/blog（两篇）。**收敛点：v1 单线程；要多 agent 就单写者 + 隔离子 agent 做情报。**

**19. Claude 原生三个上下文管理原语**〔高置信，3-0，官方 docs〕
- `compaction`（compact_20260112）：总结整段 transcript。
- `tool-result clearing`（clear_tool_uses_20250919）：把旧 `tool_result` 换成占位符、保留 tool_use 记录；**机械编辑、无推理成本**（但会破 prompt cache 前缀，下次有 cache-write 成本）。参数：`trigger`/`keep`/`clear_at_least`/`exclude_tools`/`clear_tool_inputs`。默认：trigger 100k、keep 3。
- `memory tool`（memory_20250818）：跨会话持久化，**client 端**（app 自实现后端）。
- 实测（单 demo）：峰值上下文 335k → compaction ~169k / clearing ~173k。⚠️ 单任务示意数，不外推。
- 来源：platform.claude.com docs（context-editing / compaction）+ cookbook。
- ⚠️ **OpenAI 兼容端点没有这些 server 原语，Agent Y 要在 harness 层自己实现裁剪/压缩。**

### D. Runtime / 编排 landscape（轻；⚠️ star/活跃度未独立核实，写 design 时自查）
- 编码 agent 参考实现：**SWE-agent**（Princeton，Python，"agent-computer interface"理念）、**OpenHands**（Python，开源编码 agent 平台，含沙箱/工具/loop）——可作 harness/沙箱/工具体系的行级参考。
- **Claude Agent SDK**：高层全家桶（自带 loop/工具/子agent/hooks/MCP）；我们**不用它跑核心 loop**，留作 production 参考。
- **cc-resourcecode**（本地，TS）：Claude Code 源码，`query.ts`=loop、`Tool.ts`/`tools.ts`=工具、`coordinator/`+`AgentTool`=子agent、`skills/`、`memdir/`——最贴近的行级学习参照。
- 资料集：`ai-boost/awesome-harness-engineering`、`CharlesQ9/Self-Evolving-Agents`、`EvoAgentX/Awesome-Self-Evolving-Agents`。

### E. OpenAI 侧补充（2026-06 复核：出处辨析 + 工程要点 + 与 Anthropic 异同）

**20. "harness/loop engineering 两篇论文"的出处复核**〔高置信，多源交叉，openai.com 抓取受限处经二手确认〕
- ✅ **harness engineering 是真的，但是 OpenAI 官方工程博客、不是 arXiv 论文**：《Harness engineering: leveraging Codex in an agent-first world》，作者 Ryan Lopopolo（OpenAI），约 2026-02，`openai.com/index/harness-engineering/`。主旨：3 工程师 5 个月用 Codex 产约 100 万行 / 1500 PR、人手写代码为零；工程师工作从"写代码"转向"设计让 agent 可靠产出的环境（harness）"。口号 **"Humans steer. Agents execute."**
- ❌ **loop engineering 不是 OpenAI 的**：系社区术语，由 **Addy Osmani（Google）** 命名（`addyosmani.com/blog/loop-engineering/`，2026-06），凝聚的名言出自 **Boris Cherny（Anthropic，Claude Code 负责人）"Build the loop."** 与 Peter Steinberger；**概念根在 Anthropic 一侧**，勿当 OpenAI 出版物引用。
- 血缘：context engineering（Tobi Lütke 2025-06 提出 → Anthropic 2025-09 发扬）→ harness engineering（OpenAI/Lopopolo 接着说"now it's harness engineering"）。

**21. OpenAI 官方的 loop / 停止判定**〔高置信，官方 docs〕
- run = while 循环跑到退出条件；**"final output" 判定 = 有期望类型的文本输出且本轮无工具调用**（与 code-study 发现的"只看有无 tool_use 块、别信 stop_reason"完全一致）。必设 `max_turns` 硬上限。来源：《A Practical Guide to Building Agents》(2025-04) + Agents SDK《Running agents》。
- **主动性可调参**：要更顽强放 `<persistence>`（"完全解决前别停"），要快收手降 `reasoning_effort` + 给 early-stop 标准 + escape hatch。来源：GPT-5 / GPT-5.1 prompting guide。

**22. 上下文复用：Responses API + `previous_response_id`**〔高置信，官方逐字核对〕
- "switching to the Responses API" 使 **Tau-Bench Retail 73.9% → 78.2%**（复用上一轮 reasoning、省 CoT 重建）。来源：GPT-5 prompting guide。
- ⚠️ 这是 OpenAI 第一方特性；**Agent Y 的 BYOK OpenAI 兼容端点不一定支持 `previous_response_id`/Responses API**——能用则用，不能则退回我们 harness 层自管历史（见 §C-19/②）。

**23. 工具与缓存**〔高置信〕
- 工具数量不是问题、**描述重叠才是**（成功案例管 15+ 不重叠工具，失败案例栽在 <10 个重叠工具）；尽量并行批量读改；**保持工具列表顺序稳定**（顺序变会让 prompt cache 失效——Codex 真实 bug）。来源：Practical Guide / GPT-5.1 / Unrolling the Codex agent loop。
- 编码编辑用 `apply_patch`（结构化 diff），"先读→生成 diff→只 apply 一次→失败就停下报告"。来源：GPT-5.1 guide。

**24. Guardrails 与审批（OpenAI 抽象更显式）**〔高置信，官方 docs〕
- **分层防御**：LLM 判别器 + 规则 + Moderation 叠加；按"只读/写、可逆性、权限、资金影响"给工具标**风险等级**，高风险触发人工。
- **Guardrail = 与主调用并行赛跑的独立校验器**，tripwire 命中即 raise-and-halt；用便宜模型当 guardrail 可在贵模型跑前拦截省钱。
- **审批 = 服务端发起、暂停等回复**（Codex App Server 双向 JSON-RPC，需授权动作暂停到 allow/deny）。来源：Practical Guide / Agents SDK《Guardrails》/ Unlocking the Codex harness。

**25. 单 vs 多 agent（与 Anthropic 同向）**〔高置信〕
- **先把单 agent 榨干**再拆。两种多 agent：**Manager（agents-as-tools，中心 agent 保留控制与最终答复，`agent.as_tool()`）** vs **Handoffs（单向移交控制，handoff 实现上"就是一个 `transfer_to_x` 工具"）**。手写 loop 可复刻 handoff：检测到该 tool call 就换 system prompt/agent。来源：Practical Guide / Agents SDK《Multi-agent》《Handoffs》。

**26. AGENTS.md（harness 文件工程）**〔高置信，已成开放标准〕
- AGENTS.md = 给 agent 的 README（build/test 命令、约定、目录结构），层级优先级 + `AGENTS.override.md`，现属 Linux 基金会开放标准（OpenAI/Google/Cursor 共用）。harness engineering 实践：弃巨型手册、改约 100 行"地图" + 结构化 `docs/` 当 source of truth + CI 查新鲜度；**把 lint/test 修复指引写进错误信息回灌 agent**。来源：Codex AGENTS.md guide / agents.md / Harness engineering。

**27. OpenAI vs Anthropic 异同（给 Agent Y 取舍）**〔综合〕
- **一致**：loop 都是"工具-反馈循环 + 必设硬上限"；都"先单 agent、按需上多 agent"；都重"工具少重叠 + 描述写清"。
- **侧重不同**：Anthropic 最旗帜鲜明**反框架/主张手写 loop**、把 context engineering 立为一级学科（Agent Y 哲学更贴它）；OpenAI 更"可调旋钮 + API 机制"（Responses API、persistence/effort 旋钮、guardrail tripwire 抽象、App Server 会话协议）。
- **可直接搬 OpenAI 的具体机制**：(1) 退出判定"无工具调用的期望类型文本" + 硬 max_turns；(2) guardrail 并行赛跑 + tripwire + 工具风险分级 + 审批暂停门（正好喂 PRD F8.4）；(3) 多 agent 起步用 agents-as-tools 保留控制；(4) AGENTS.md 当"地图" + 错误信息回灌修复指引；(5) 工具列表顺序稳定利缓存。

---

## ② 给 Agent Y 的可落地设计建议

### Memory

> ⚠️ **实践校准（2026-06，源自 `docs/code-study-cc.md §6/§8`）**：通读 Claude Code 生产源码后发现，它的记忆系统**没有向量数据库、没有 `α·β·γ` 加权公式**——用的是「markdown 文件 + frontmatter 描述 + 让一个小模型挑出 ≤5 条 + 把时近性写成『47 天前保存』的人话喂给大模型」。下面 v1 建议**据此简化**：把"向量索引 + 三权重"从 v1 必选**降级为后置增强**，v1 改用"小模型挑选"。学术上的加权召回（Generative Agents，见 §①-3）仍是正确发现、作为演进期参考保留。

**v1 最小可信版（按实践校准后）**
- **存储两件套（v1）**：① 一条记忆 = 一个 markdown 文件（frontmatter `name/description/type` + 正文）；② `MEMORY.md` 常驻索引（一行一指针，设行/字节上限）。**SQLite 仅按需当 mtime/路径缓存，向量索引 v1 不做**（抄 cc-resourcecode `memdir/`）。
- **记忆类型**：直接采用 Claude Code 四类 taxonomy——`user`（角色/偏好）/ `feedback`（工作方式指导，带 Why）/ `project`（进行中工作/决策的"为什么"）/ `reference`（外部系统指针）；提示词可借鉴（已被其 eval 反复打磨）。仍保留 episodic/semantic/procedural 作为概念映射。
- **写入端过滤是重心**：明确"什么该存/不该存"——**不存能从代码/git 当场查到的东西**（代码模式、架构、文件路径、调试 recipe），否则会过时变误导。这条比"事后算重要性分"性价比高得多。
- **召回（v1）**：扫各文件 frontmatter（按 mtime 倒序截断候选）→ **让一个便宜模型挑 ≤5 条**（不确定就别选）→ 读出注入，附"saved N days ago"文本由大模型自行判断陈旧性。**不调 α/β/γ 三权重**。
- **反思 / 自动沉淀**：编码场景用**环境式**（测试失败信号作锚）；机制抄 Claude Code——每轮结束 **fork 一个受限子 agent**（只读 + 只能写 memory 目录、限 turn、与主 agent 当轮互斥、强制先查重）按 taxonomy 提炼。
- **与自进化打通**：反思产出的"经验条目"= 自进化的 **few-shot 记忆候选**，经验证集验证后才并入。

**演进路径**：v1 文件 + 小模型挑选 → 记忆量变大、挑选不准时再上**向量索引召回**（sqlite-vec/Chroma）与 `α·相关性+β·时近性+γ·重要性` 加权（Generative Agents 式）→ A-MEM 式写入时更新旧记忆 → H-MEM 分层路由。
**坑**：① 别用长上下文替代记忆层；② JIT 用混合（少量预载 + 按需检索）；③ 保持系统提示/工具列表前缀稳定，利于 prompt cache。

### 自进化闭环
**v1 最小可信版（编码场景，可量化）**
1. **Environment（真值源）**：编码任务集 + Docker 沙箱跑测试 → pass/fail（客观分）。
2. **输入**：失败轨迹（从 Langfuse trace 取）。
3. **归因分类**：工具用错 / 上下文缺失 / prompt 不清 / 模型能力不足。
4. **Optimiser（轻量）**：生成改进候选——改 system prompt 片段 / 加 few-shot 记忆 / 调工具 description。
5. **回归验证**：在**留出验证集**重跑，**只升不降才合并**，记录 diff + 提升幅度，**可回滚**。
6. **产出**：pass@1 随 iteration 的**提升曲线** + 可解释改进记录（面试核心素材）。

**演进路径**：DSPy 自动 prompt/程序优化 → 搜索式自动设计 / RL（反思遇瓶颈再上）。

### Loop & Harness（M1）
- **结构**：单线程 **act-observe** loop（v1 先单线程最稳）；子 agent 留演进期，且遵守"单写者 + 隔离子 agent 只回传摘要"。
- **停止/退出判定**：**主信号 = 本轮有无 tool_use 块**（无工具调用 + 文本达预期 → 完成）；**别只信 stop_reason**（code-study 与 OpenAI Practical Guide/Agents SDK 双重佐证，§C-21/§8）。再叠 `max_turns` 硬上限 + token/预算多重保险防死循环。
- **错误恢复**：工具失败回灌 `is_error` 让模型自调整（错误即消息、不抛异常中断 loop）；设重试上限。
- **ground truth + self-verify**：Docker 跑测试 = 每步真值；要求"测试通过才算完成"。
- **上下文/工具结果管理**：v1 可先全保留；长了再做 tool-result clearing + 完整压缩。⚠️ **OpenAI 兼容端点无 server 原语，全在 harness 层自实现**——配方见 `code-study-cc.md §2`（effective 窗口−13k 触发 / 工具结果换占位串 KEEP_RECENT=5 / 9 段式摘要 / 保留≥10k且≥5条上限40k不切断配对）。能用第一方 Responses API/`previous_response_id` 复用推理则用（Tau-Bench +4.3pt，§C-22），不能则退回自管历史。
- **context engineering**：系统提示 + **工具列表顺序稳定**（缓存友好，§C-23）；工具描述写"**何时用**"而非只"做什么"，且少重叠；JIT 混合加载。
- **guardrails / 审批（喂 PRD F8.4）**：并行赛跑的独立校验器 + tripwire 即停 + 工具按只读/可逆/权限/资金**风险分级** + 高风险审批暂停门（§C-24）。
- **多 agent 起步形态**：先 **agents-as-tools（manager 保留控制）**，需会话级移交再上 handoff（handoff 实现上=一个 `transfer_to_x` 工具，§C-25）。
- **AGENTS.md 当"地图"**：约 100 行目录 + 结构化 `docs/` 当 source of truth；**把 lint/测试修复指引写进错误信息回灌上下文**（§C-26）。
- **对照 cc-resourcecode/query.ts**：✅ 已完成行级走读，见 `docs/code-study-cc.md`（loop/压缩/工具/子agent/技能/记忆 6 子系统 + §7 v1 借鉴清单）。

### 模块划分（对齐 PRD/design）
`core`（loop·llm/provider·tool·types）· `memory`（store·recall·reflection）· `obs`（tracer→Langfuse）· `eval`（harness·improve）· `sandbox`（docker）· `scenarios`（coding 先）。
**Java 候选**（边界清晰、可独立交付、简历值钱）：沙箱执行器服务 / 待办提醒后端（Spring Boot），经 API 契约与 Python 核心解耦。

---

## ③ 参考清单

### 论文（年份 / 一句话 / 对我们的用处）
| 论文 | 年 | 一句话 | 用处 | Python repo |
|---|---|---|---|---|
| Generative Agents `arXiv:2304.03442` | 2023 | memory stream + 加权召回 + 反思 | **v1 召回与反思直接照搬** | — |
| MemGPT `arXiv:2310.08560` | 2023 | OS 式分层虚拟上下文 | 跨会话/分层思路 | Letta（原 MemGPT） |
| Reflexion `arXiv:2303.11366` | 2023 | 语言反思驱动自我改进 | v1 反思机制（综述级确认） | 有 |
| Self-Refine `arXiv:2303.17651` | 2023 | 自反馈迭代精炼输出 | 自进化候选生成思路 | 有 |
| Lost in the Middle `arXiv:2307.03172` | 2023 | 长上下文 U 形注意力衰减 | 为何需独立记忆层 | — |
| A-MEM `arXiv:2502.12110` | 2025 | 结构化记忆笔记 + 记忆演化 | 记忆**演进期**首选 | `agiresearch/a-mem` |
| H-MEM `arXiv:2507.22925` | 2025 | 分层路由记忆 | 记忆量大时 | — |
| Self-Evolving Agents 综述 `arXiv:2507.21046` | 2025 | 自进化框架（进化什么/何时/如何/在哪） | 自进化术语与框架 | `CharlesQ9/Self-Evolving-Agents` |
| Self-Evolving AI Agents 综述 `arXiv:2508.07407` | 2025 | 统一反馈回路四组件 | 自进化设计骨架 | — |
| Memory 综述 `2603.07670`/`2602.06052`/`2605.06716` | 2026 | 三轴分类/存储谱/召回反思 | 记忆"设计语言" ⚠️新预印本 | — |

### 一手工程文章（强烈建议精读，面试常问）
| 文章 | 团队 | 用处 |
|---|---|---|
| Building effective agents | Anthropic 2024 | **loop 地基**：act-observe / 停止条件 / 最简方案 / workflow vs agent |
| Effective context engineering for AI agents | Anthropic 2025 | context 实践：注意力预算 / JIT 混合 / compaction / 子 agent 隔离 |
| Effective harnesses for long-running agents | Anthropic 2025 | 编码长任务：两段式 / progress+git / self-verify / compaction 不够 |
| Writing tools for agents | Anthropic | 工具设计原则 |
| Don't build multi-agents / When multi-agents work | Cognition 2025–26 | 多 agent 争论与 2026 收敛（单写者+情报型子agent） |
| Context Rot | Chroma | 上下文越长越退化的实测 |
| Claude docs: context-editing / compaction / prompt-caching + 工程 cookbook | Anthropic | **原生上下文管理原语 + 参数默认值**（Claude 侧直接可用） |
| A Practical Guide to Building Agents (PDF) | OpenAI 2025-04 | loop 退出条件 / 工具三类 / guardrails / manager vs handoff |
| GPT-5 & GPT-5.1 prompting guide | OpenAI 2025 | 主动性旋钮(persistence/effort) / Responses API 复用推理(+Tau-Bench) / apply_patch |
| Agents SDK docs（running/handoffs/guardrails/sessions/multi-agent） | OpenAI | loop/handoff/guardrail tripwire/session 钩子的权威定义 |
| Harness engineering（Lopopolo）/ Unrolling the Codex agent loop / Unlocking the Codex harness | OpenAI 2026-02 | harness 实践 / Codex 真实 loop / 缓存与压缩 / App Server 会话协议(thread·turn·item)·审批暂停。⚠️ openai.com 抓取受限，措辞以原页为准 |
| AGENTS.md 标准（agents.md，Linux 基金会） | 开放标准 | 给 agent 的"地图"文件规范 |

### 代码参考（⚠️ star/活跃度/上手难易未独立核实，落地前自查 GitHub）
| repo | 语言 | 用处 |
|---|---|---|
| `SWE-agent`（Princeton） | Python | 编码 agent + agent-computer interface 参考 |
| `OpenHands` | Python | 开源编码 agent 平台：沙箱/工具/loop |
| `agiresearch/a-mem` | Python | A-MEM 记忆实现 |
| `cc-resourcecode`（本地） | TS | Claude Code 源码：loop/工具/子agent/memory 行级参照 |
| `ai-boost/awesome-harness-engineering` | — | harness 工程资料集 |
| 记忆库（**未核实**，待自查）：mem0 / Zep·Graphiti / Cognee / LangMem / Letta | 多为 Python | v1 向量+结构化记忆可能直接复用其一 |

---

## ④ Caveats（务必读）与待补清单

**可信度边界**
- 多条记忆"分类法"结论来自 **2026 年很新的非同行评审预印本**——当"业界怎么描述"用恰当，别当实证定论。
- "**长上下文 ≠ 记忆**"为 2-1 分裂票：方向可信，**不引任何具体百分比**。
- **多 agent 是活跃争论**（12 个月内处方就从"别建"软化到"单写者+情报型"），别当尘埃落定的共识。
- Anthropic / Cognition 多为**厂商/团队博客**，有推广动机；"compaction 不够→需脚手架""生产级 web app"未做独立量化基准；335k→170k 是**单 demo 数，不外推**。
- 自进化的 Reflexion/Self-Refine/DSPy/ADAS 等**仅综述级确认**，未逐篇逐字核验。

**待补（建议在写 `design.md` 时各补一轮快速核实）**
1. ✅ **已完成** — **OpenAI 兼容端点下如何自实现 compaction / tool-result clearing / memory**：见 `code-study-cc.md §2`（带默认数值的完整配方）。← 最影响 BYOK 架构。
2. **具体开源记忆库选型**（mem0 / Zep·Graphiti / Cognee / LangMem / Letta 的架构差异、是否 Python、star/活跃度、上手难易）——决定 v1 记忆是自写还是复用。⚠️ 优先级下降：code-study 证明纯文件方案够用，向量库后置。
3. ✅ **已完成** — **cc-resourcecode 代码走读**：见 `code-study-cc.md`（不止 query.ts，扩展到 6 子系统 + 行级借鉴/忽略清单）。
4. **Langfuse trace 如何反哺自进化闭环**（trace → eval 样本的 schema 映射）。
5. **系统提示/工具描述"何时用"模板 + prompt 注入/上下文中毒防护**的可抄示例。
6. ✅ **部分完成** — **tool search / 渐进披露**：工具侧 + 技能侧机制见 `code-study-cc.md §3/§5`；剩"工具数巨大时的开销基准"待测。

**出处复核（2026-06）**：用户问的"OpenAI harness / loop engineering 两篇论文"已查实——**harness engineering 真**（OpenAI 工程博客 by Lopopolo，非 arXiv 论文，§E-20）；**loop engineering 非 OpenAI**（Addy Osmani/Google 命名，概念根在 Anthropic，§E-20）。

---

*本报告由两轮 deep-research（A: 104 agent / B: 107 agent，合计 ~400 万 token、48 来源、50 条经核对结论）合成；2026-06 追加 OpenAI 侧复核轮（§E，查实 harness/loop 出处 + 官方工程要点）与 `code-study-cc.md`（Claude Code 源码走读，校准了 Memory v1 配方）。原始产物存于会话 task 输出。*
