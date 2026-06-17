# 开发环境与运行指南（M1）

> 给两位开发者的"上手即用"说明。改动前先读 `docs/design.md`（设计/接口契约）与 `AGENTS.md`（约定）。

## 1. 环境要求
- **Python 3.12+**
- **Docker**（用真沙箱跑代码时需要；本机已验证 Docker Engine 29.x 可用）。没有 Docker 也能开发——用 `--sandbox local`，且 Docker 相关测试会自动跳过。
- git

## 2. 安装
```bash
cd agent_Y
python -m venv .venv && source .venv/bin/activate   # 可选但推荐
pip install -e ".[dev]"      # 核心 + 测试依赖（pytest 等）
# 可选 extras：
pip install -e ".[office]"   # 办公文档 skills（python-docx/pptx/openpyxl，M5）
pip install -e ".[obs]"      # Langfuse（M2）
```
`docker` SDK 已在主依赖里；要跑 Docker 沙箱还需本机装好并启动 Docker daemon。

## 3. 跑测试
```bash
pytest -q
```
- 全过即环境 OK（当前 28 个）。
- `tests/test_docker_sandbox.py` 在**没有可用 Docker 时自动跳过**；有 Docker 时会真起容器验证。
- `examples/` 里有一个**故意失败**的样例（修复练习用），已通过 `testpaths=["tests"]` 排除，不会被误收。

## 4. 离线体验（无需 API key / Docker）
```bash
python scripts/demo_loop.py
```
用 MockProvider 驱动 agent loop：建文件 → 读回 → 完成，能直观看到"调工具 → 回灌结果 → 停止"。

## 5. 跑真实编码任务（CLI）
```bash
export ANTHROPIC_API_KEY=sk-...          # 必需（接真模型）

# 用本机目录当 workspace；默认 local 沙箱（开发友好）
python -m cli.main run "修复 calculator.py 里失败的测试" \
  --workspace examples/fix_failing_test --yes

# 用 Docker 沙箱（隔离更安全，模型生成的代码只在容器内跑）
python -m cli.main run "<任务>" --workspace <你的项目目录> --sandbox docker --yes

# DeepSeek（OpenAI 兼容端点，已用真 key 实测可用）
export DEEPSEEK_API_KEY=sk-...
python -m cli.main run "<任务>" --provider openai --base-url https://api.deepseek.com \
  --model deepseek-chat --api-key-env DEEPSEEK_API_KEY --workspace <项目目录> --yes
```

> **Provider 选择**：`--provider anthropic`（默认，读 `ANTHROPIC_API_KEY`）或 `--provider openai`（OpenAI 兼容端点，配 `--base-url` + `--api-key-env`，覆盖 DeepSeek/GPT/本地 Ollama 等）。**密钥只从环境变量读，绝不写进文件/日志/trace**（PRD F8.1）。
参数：`--workspace` 工作目录（默认临时目录）｜`--model` 模型 id（默认 `claude-sonnet-4-6`）｜`--sandbox local|docker`｜`--yes` 自动放行写/危险操作（不加则每次写操作交互确认）。

> 若 SDK 对 `thinking`/`output_config` 参数报错：`core/providers/anthropic.py` 里 M1 默认**关** thinking，可按你的 anthropic SDK 版本微调（见该文件注释）。

## 6. Docker 沙箱说明（`core/sandbox/docker.py`）
- **镜像**：默认 `python:3.12-slim`。首次用前建议手动拉一次：`docker pull python:3.12-slim`。
- **隔离**：每个 `DockerSandbox` 起一个容器，**默认关网络**（`network_disabled=True`）、限 CPU/内存（默认 1 cpu / 512m）；`close()` 会删容器。
- **接口**：实现 `SandboxExecutor`（`exec` / `write_files` / `read_file`），与 `LocalExecutor` 同接口——**换沙箱不改 tools**。
- **验证**：`pytest tests/test_docker_sandbox.py -q`（已实测：写/执行/读/跑 python/默认断网均通过）。

## 7. 已知限制（M1）/ 待办
- **容器默认断网** → 容器内 `pip install` 装不了依赖。跑需要第三方库的编码任务时，二选一：① 用一个预装好依赖的自定义镜像；② 等 M2 支持"按任务放行网络"（`exec(network=True)` 目前 DockerSandbox 未透传，TODO）。本机/可信项目可先用 `--sandbox local`。
- `exec` 的 `timeout` 在 DockerSandbox 里**尚未强制 kill**（TODO M1 收尾）。
- 镜像架构跟随本机（本机为 arm64）；换机注意拉对应架构镜像。
- **OpenAICompatProvider 已用 DeepSeek 真 key 实测通过**（完整跑通"读→测失败→改→测通过"闭环）。AnthropicProvider 未用真 key 实测；thinking+signature 回传留到 M2。

## 8. 协作约定（详见 `docs/design.md §8.3/§8.4`）
- 分支 `feat/<模块>-<简述>`；提交 `类型(范围): 说明`；`main` 走 PR + 对方 review。
- **接口契约在 `docs/design.md §4` + 各 `core/*/base.py`，是冻结面**：改 Protocol → PR 标题带 `[contract]` + @ 对方 + 双确认。
- 分工提案见 `design.md §8.4`（A=Agent 内核/编排/前端；B=工具/沙箱/server/scheduler/Java）。
- M1 任务清单：`docs/m1-issues.md`。

## 9. 常见问题
- **`docker` 命令报 permission denied**：把用户加入 docker 组（`sudo usermod -aG docker $USER` 后重登），或用 sudo 跑。
- **`Cannot connect to the Docker daemon`**：Docker 没启动（`sudo systemctl start docker` 或启动 Docker Desktop）。
- **`image not found` / 拉取慢**：先 `docker pull python:3.12-slim`；国内可配镜像加速。
- **`ANTHROPIC_API_KEY` 未设置**：CLI 会提示；先 `export`，或用 `scripts/demo_loop.py` 离线体验。
