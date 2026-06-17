# Agent Y — 会编码、能自进化的个人桌面工作助手

> 本地优先的桌面 AI Agent：自带模型 API（**BYOK** 多 Provider），既能做**编码任务**（沙箱内改代码、跑测试直到通过），也能当**个人工作助手**（待办提醒、本地文件问答、办公文档 Word/PPT/Excel、网络检索起草）。每一步执行**全链路可观测**，并用 **Eval 自进化闭环**越用越准。既是简历项目，也要真能日常自用。

> **产品重心**：编码为锤（自进化的客观锚点）、助手紧随。
> **设计指北针**：站在 harness / loop / context engineering + 自进化 + memory 的优秀论文与开源项目，以及 Claude Code 源码（`cc-resourcecode/`）行级走读这些"巨人肩膀"上。

## 开发阶段（软件开发六阶段）

| 阶段 | 状态 | 产出 |
|---|---|---|
| ① 需求分析 | ✅ **定稿** | `docs/PRD.md` v1.0 + §8 原型图 |
| ② 系统设计 | 🚧 **进行中** | `docs/design.md`（架构 / 接口契约 / 数据模型 / M1 拆解）|
| ③ 编码开发 | 🚧 **M1 完成 + M2 后端进行中** | M1：内核+CLI（DeepSeek 真机实测）；M2：FastAPI server/SSE/会话持久化/审批；**37 测试通过** |
| ④ 测试 | ⬜ | 测试用例 / 报告 |
| ⑤ 部署上线 | ⬜ | 打包 `.app` / 部署文档 |
| ⑥ 运维维护 | ⬜ | 监控 / 迭代 |

## 文档索引（改动前先读对应文档）

| 文档 | 作用 |
|---|---|
| [`docs/HANDOVER.md`](docs/HANDOVER.md) | **🤝 交接文档：接手先读这份** —— 现状 / 五分钟上手 / 代码地图 / 关键决策 / 已完成vs待办 / 下一步 / 安全注意 |
| [`docs/PRD.md`](docs/PRD.md) | **需求**：目标 / 用户故事 / 功能 / 原型图 / 里程碑 / MVP DoD / 决策。技术栈与范围以此为准 |
| [`docs/design.md`](docs/design.md) | **系统设计**：架构、**§4 接口契约**（前后端 REST+SSE / Provider / Tool / Sandbox / Memory）、数据模型、M1 拆解。两人协作的冻结面 |
| [`docs/research.md`](docs/research.md) | **调研**：memory / 自进化 / harness·loop·context engineering 业界做法 + OpenAI 侧复核 + 术语表，带引用 |
| [`docs/code-study-cc.md`](docs/code-study-cc.md) | **源码借鉴**：Claude Code 6 子系统行级走读 + Agent Y 借鉴/忽略清单 |
| [`docs/dev-setup.md`](docs/dev-setup.md) | **开发/运行指南**：安装、跑测试、CLI、**Docker 沙箱**、排错、协作约定 |
| [`docs/m1-issues.md`](docs/m1-issues.md) | M1 任务清单（13 项，可转 GitHub Issues）|
| [`docs/plan.md`](docs/plan.md) | 早期落地计划，**已被 PRD/design 取代**，留作历史参考 |

## 快速开始（M1）

```bash
pip install -e ".[dev]"          # 安装
pytest -q                        # 27 个测试应全过
python scripts/demo_loop.py      # 离线看 agent loop 调工具→回灌→完成（无需 API/Docker）

# 接真模型跑编码任务（修复一个故意写错的测试）：
export ANTHROPIC_API_KEY=sk-...
python -m cli.main run "修复 calculator.py 里失败的测试" --workspace examples/fix_failing_test --yes
```

## 技术栈（详见 PRD / design）

Python + FastAPI 核心 · `anthropic` + `openai`（兼容端点）· Pydantic（工具 schema）· Docker（沙箱）· Langfuse（可观测）· `keyring`（密钥）· Web 前端 + pywebview → 打包 macOS `.app`/`.dmg`（不做语言重写）。

## 说明

- `cc-resourcecode/` 是 Claude Code 源码，**仅本地学习参考、已 gitignore**，不纳入版本控制。
- `docs/CLAUDE-FABLE-5.md` 为参考材料（模型系统提示词），建议归入 `references/`（待团队确认）。
- 团队：2 人（作者 + 1 位同事）；分工见 `design.md §8.4`（待确认）。
