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
`coding-v1`：两个故意写错的小模块（加法用了减号、问候语用错词），用于点亮 pass@1 与自进化曲线。
