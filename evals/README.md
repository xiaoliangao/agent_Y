# 编码 Eval 任务集

每个任务一个目录：`<taskset>/<task_id>/`，内含 `meta.json`（`{prompt, test_cmd}`）+ 该任务的工作区文件。
`test_cmd` 退出码 0 = 通过（客观真值）。`meta.json` 不会被复制进沙箱，其余文件会。

跑分 / 自进化（需配好 provider，见 `docs/dev-setup.md`）：
```bash
python -m cli.main eval    --taskset evals/coding-v1 --provider openai --base-url https://api.deepseek.com \
  --model deepseek-chat --api-key-env DEEPSEEK_API_KEY
python -m cli.main improve --taskset evals/coding-v1 --provider openai --base-url https://api.deepseek.com \
  --model deepseek-chat --api-key-env DEEPSEEK_API_KEY
```
`coding-v1`：两个故意写错的小模块（加法用了减号、问候语用错词），简单 bug，capable 模型基线即满分。

`coding-hard`：**带隐藏测试 + 欠规格 prompt** 的任务（median 偶数取下中位、round 用 half-up 而非银行家舍入）。
评分用的 `_hidden/` 测试 agent 看不到，且 prompt 故意不说这些"反直觉约定"——所以模型**基线会失败**，
正是用来演示「自进化据失败学经验 → pass@1 提升」的曲线。多轮：`improve --rounds N`。
