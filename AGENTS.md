# AGENTS.md — Agent Y 项目地图

> 给 AI agent 和新成员的"地图"（约定俗成的 [AGENTS.md](https://agents.md) 规范）。**source of truth 是 `docs/`**；改动前先读对应文档。Agent Y 自己跑编码任务时也读本文件。

## 这是什么
会编码、能自进化的个人桌面工作助手。Python + FastAPI 核心，CLI 先行 → pywebview 桌面 app。详见 `README.md` 与 `docs/PRD.md`。

## 目录
- `core/` — Agent 内核：`types` / `loop` / `engine` / `providers` / `tools` / `harness` / `memory` / `obs` / `eval` / `sandbox` / `scheduler` / `scenarios`
- `server/` — FastAPI REST+SSE（仅翻译 HTTP↔Engine）
- `cli/` — 命令行入口（`agenty`）
- `tests/` — 测试
- `agents/` `skills/` — 子 agent / 技能定义文件
- `agent-y/` — **前端 demo**（Vite/React，throwaway；M2 正式整合时再定框架）
- `docs/` — 需求/设计/调研（**source of truth**）

## 命令
```bash
pip install -e ".[dev]"     # 安装（含测试依赖）
pytest                      # 跑测试
ruff check .                # lint
agenty run "<任务>"         # 跑 CLI（M1 目标）
```

## 约定（务必遵守）
- **接口契约在 `docs/design.md §4`，是冻结面**：改任何 `*/base.py` 的 Protocol → PR 标题带 `[contract]` + @ 对方 + 双确认。
- 跨模块只通过 `base.py` 的 Protocol + Pydantic 数据类对接（design §0）。
- 安全默认 **fail-closed**；工具/校验失败"回灌错误、不抛异常中断 loop"。
- 密钥只进 OS keychain，**绝不**明文落库/进日志/进 trace。
- 分支 `feat/<模块>-<简述>`；提交 `类型(范围): 说明`；`main` 走 PR + review。

## 当前阶段
**阶段③ 编码（M1）**。任务见 `docs/m1-issues.md`。M1 验收：CLI 给编码任务 → Docker 沙箱把失败测试改绿、写操作先确认。分工见 `docs/design.md §8.4`。

**环境/安装/Docker/排错见 `docs/dev-setup.md`**。Docker 沙箱已在本机实测可用（`pytest tests/test_docker_sandbox.py`）。
