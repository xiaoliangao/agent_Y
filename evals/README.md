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

## 事务类 Eval（PRD F4.4，半客观）

起草/总结/问答这类任务没有 exit code 当真值，故用 **规则分（硬约束）+ LLM-judge 分（对照 rubric）** 综合打分。
任务目录同样是 `<taskset>/<task_id>/meta.json`，但字段是：
```json
{
  "prompt": "交给助手的任务",
  "criteria": "给 judge 的评分要点（自然语言）",
  "rules": [{"type": "contains", "value": "支付"}, {"type": "min_len", "value": 30}],
  "pass_threshold": 0.6,
  "rule_weight": 0.4
}
```
规则 `type`：`contains` / `not_contains` / `regex` / `min_len` / `max_len` / `any`(列表任一) / `all`(列表全部)。
综合分 = `rule_weight*规则分 + (1-rule_weight)*judge 分`（无 rules 时退化为纯 judge），≥ `pass_threshold` 算通过。
判分模型走 F1.4 的 **eval-judge 角色**（`--judge-model`，默认同 `--model`）。

```bash
python -m cli.main eval-assistant --taskset evals/assistant-v1 --provider openai \
  --base-url https://api.deepseek.com --model deepseek-chat --api-key-env DEEPSEEK_API_KEY \
  --judge-model deepseek-reasoner
```
`assistant-v1`：3 个自包含任务（周报起草 / 一句话总结 / 婉拒邮件），无需参考文件，capable 模型基线即可过。
