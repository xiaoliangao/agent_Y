# 样例：修复失败的测试（M1 验收用例）

一个故意写错的 `add`（用了减号）+ 一个失败测试。用来验证 Agent Y 的编码闭环：
agent 读代码 → 跑测试看失败 → 改代码 → 再跑测试转绿。

**真模型跑**（需 `ANTHROPIC_API_KEY`）：
```bash
agenty run "修复 calculator.py 里失败的测试" --workspace examples/fix_failing_test
```

**离线 e2e 测试**（MockProvider 脚本驱动，验证工具+loop 能修好）：见 `tests/test_e2e_coding.py`。
