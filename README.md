# Agent Y

> 本地优先的个人桌面 AI 助手（macOS）。**自带模型 Key（BYOK，支持 Claude / DeepSeek / OpenAI 兼容端点）**，
> 既是**日常助手**（对话、待办、天气、本地文件问答、办公文档、网络检索、技能库），也是**编码 IDE**（打开文件夹、读改代码、跑测试、彩色 diff 审阅）。
> 数据只存在你本机，API Key 进系统钥匙串。

---

## 下载安装

1. 到 [**Releases**](../../releases) 下载最新的 `Agent-Y-x.y.z.dmg`。
2. 双击打开，把 **Agent Y** 拖进 **Applications**。
3. 首次打开：在「应用程序」里**右键 Agent Y → 打开**（应用未做 Apple 签名，需放行一次；之后正常双击）。

> 想后台常驻：关掉窗口会**收进菜单栏**（顶部 **Y** 图标），后端继续跑（定时提醒不断）；点图标可重新开窗，「退出」才真正关闭。

## 首次使用

1. 打开后点左下「**设置**」→「模型连接」→ 填一个 Provider 的 **API Key**（Claude 官方 / DeepSeek / Kimi / OpenAI / 本地 Ollama…），选默认模型，测连接。
2. （可选）「人设与偏好」里填**天气城市**、按角色配模型。
3. 开始用：
   - **助手**：直接对话；右侧是今日天气 + 待办；📎 可授权一个文件夹让它读。
   - **编码**：切到「编码」进入 IDE —— 打开文件夹 / 新建文件 / 看代码（语法高亮）/ agent 改动自动高亮成 diff，可保留或撤销。
   - **技能**：左栏「技能」可**安装技能包**（含 `SKILL.md` 的文件夹，可带脚本）；遇到相关任务，助手会自动调用。
   - **自动化**：定时跑任务、产出进待审队列。

## 能做什么

- **日常助手**：对话、待办/提醒、天气与出行建议、授权目录内的文件问答、Word/PPT/Excel 生成、网络检索与起草。
- **编码 IDE**：打开任意项目文件夹，读/改/跑测试；彩色 diff 逐文件保留或撤销；可切 Docker 沙箱隔离。
- **技能（渐进披露）**：装好的技能平时只占极小上下文，命中任务才加载完整步骤（含运行附带脚本）。
- **可观测 + 自进化 Eval**：执行全程可追踪；编码任务可跑 Eval、据失败自动改进（CLI）。
- **隐私**：全本地，Key 进钥匙串；联网仅限你触发的检索 / 天气。

## 数据位置

所有运行数据在 **`~/.agenty/`**：会话/消息(`agenty.db`)、待办与自动化(`scheduler.db`)、连接(`providers.db`，**不含 Key**)、设置(`settings.json`)、记忆(`memory/`)、技能(`skills/`)、授权目录(`folders.json`)、日志(`desktop.log`)。**API Key 只在 macOS 钥匙串**。备份直接拷该目录即可。

---

## 从源码构建（开发者）

```bash
# 环境：macOS、Node 18+、Python 3.10+（推荐 conda 环境）
pip install -e ".[dev]"        # 装依赖
pytest -q                      # 跑测试

# 打成安装包（产物 dist/Agent-Y-<版本>.dmg）：
bash scripts/build_dmg.sh      # 内部会先构建前端 + .app 再打 dmg
```

打 `v*` 标签会触发 `.github/workflows/release.yml`，在 GitHub Actions(macOS) 上自动构建 `.dmg` 并挂到对应 Release：

```bash
git tag v0.1.0 && git push origin v0.1.0
```

技术栈：Python + FastAPI 内核 · `anthropic`/`openai`(兼容端点) · Pydantic · Docker(沙箱) · `keyring`(密钥) · Web 前端(Vite/React) + pywebview/rumps → PyInstaller 打包 `.app`/`.dmg`。

更多设计/约定见 [`docs/`](docs/)：`HANDOVER.md`（上手）、`PRD.md`（需求）、`design.md`（架构与接口契约）、`packaging.md`（打包细节）、`dev-setup.md`（开发/Docker/排错）。
