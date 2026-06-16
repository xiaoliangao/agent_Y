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
2. **Memory 必须是独立的一层，不能靠大上下文窗口糊弄**——长上下文 ≠ 记忆。v1 用 **向量检索 + 结构化/文件 + "相关性·时近性·重要性"加权召回 + 阈值/事件触发反思** 即可做到可信且能长大。
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

---

## ② 给 Agent Y 的可落地设计建议

### Memory
**v1 最小可信版**
- **存储三件套**：① SQLite（结构化：会话、任务、记忆条目元数据）；② 一个**本地可跑的向量索引**（如 sqlite-vec / Chroma / FAISS，BYOK 本地优先，选轻依赖的）；③ 纯文件 `MEMORY.md`（人类可读的 notes，借 cc-resourcecode `memdir/` 的索引+详情思路）。
- **记忆类型**：episodic（任务/会话发生的事）+ semantic（用户事实/偏好）+ procedural（常用事务沉淀的 skill）。
- **写入**：每次任务/会话结束写 episodic；显式事实写 semantic。
- **召回**：`α·相关性 + β·时近性 + γ·重要性`，v1 三系数=1（直接抄 Generative Agents）。
- **反思**：编码场景用**环境式**（测试失败信号作锚）生成"经验条目"；通用场景用阈值/会话结束触发。
- **与自进化打通**：反思产出的"经验条目"= 自进化的 **few-shot 记忆候选**，经验证集验证后才并入。

**演进路径**：A-MEM 式结构化笔记 + 写入时更新旧记忆 → 跨会话 progress 文件 + git（借 long-running harness）→ 记忆量大再上 H-MEM 分层路由。
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
- **停止**：`max_steps` + token/预算 + `end_turn`，多重保险防死循环。
- **错误恢复**：工具失败回灌 `is_error` 让模型自调整；设重试上限。
- **ground truth + self-verify**：Docker 跑测试 = 每步真值；要求"测试通过才算完成"。
- **上下文/工具结果管理**：v1 可先全保留；长了再做 tool-result clearing（参照 Claude 默认 trigger 100k / keep 3）。⚠️ **OpenAI 兼容端点要在 harness 层自实现这套**（无 server 原语）。
- **context engineering**：系统提示稳定（缓存友好）；工具描述写"**何时用**"而非只"做什么"；JIT 混合加载。
- **对照 cc-resourcecode/query.ts**：借鉴其 loop 主循环、工具分发、子 agent fork、memdir；v1 砍到最小。（⚠️ 需做一次 query.ts 代码走读才能给行级"哪段抄/哪段简化"——见待补。）

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
1. **OpenAI 兼容端点下如何自实现 compaction / tool-result clearing / memory**（无 server 原语时，客户端裁剪阈值 + prompt-cache 友好前缀策略）。← 最影响 BYOK 架构。
2. **具体开源记忆库选型**（mem0 / Zep·Graphiti / Cognee / LangMem / Letta 的架构差异、是否 Python、star/活跃度、上手难易）——决定 v1 记忆是自写还是复用。
3. **cc-resourcecode `query.ts` 代码走读**：给"哪段照抄、哪段简化为 v1"的行级建议。
4. **Langfuse trace 如何反哺自进化闭环**（trace → eval 样本的 schema 映射）。
5. **系统提示/工具描述"何时用"模板 + prompt 注入/上下文中毒防护**的可抄示例。
6. **tool search / 渐进披露**在工具多时的检索机制与开销。

---

*本报告由两轮 deep-research（A: 104 agent / B: 107 agent，合计 ~400 万 token、48 来源、50 条经核对结论）合成。原始产物存于会话 task 输出。*
