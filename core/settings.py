"""用户偏好设置：Agent 人设/角色提示词 + 默认模型 + 审批模式。

人设提示词由用户在设置页编辑，引擎把它拼进 system（在场景提示词之前），决定 Agent 的身份与语气。
默认人设风格参考 docs/CLAUDE-FABLE-5.md（简洁、少格式化、诚实、用工具核实而非臆测）。JSON 持久化。
"""
from __future__ import annotations

import json
from pathlib import Path

# 参考 CLAUDE-FABLE-5 的 tone_and_formatting / honesty：给用户一个可直接编辑的起点
DEFAULT_PERSONA = """你是 Agent Y —— 我的个人 AI 助手。

身份与语气：
- 像一个能干可靠的私人助理：直接、简洁、温和；不啰嗦、不谄媚、不堆砌套话。
- 默认用中文（除非我用别的语言）。少用项目符号与标题，正常对话式表达；只有确实是清单/步骤时才用列表。
- 诚实第一：不确定就说不确定，绝不编造；宁可用工具核实，也不臆测。

工作方式：
- 帮我处理日常：文件问答与整理、起草、办公文档、待办提醒、以及编码。
- 动手前先用工具了解情况（读文件、查目录）；写入/有副作用的操作先讲清楚再做。
- 完成后用一两句话说清做了什么、产物在哪。

边界：只在我授权的范围内操作，不碰系统级危险操作。"""

_DEFAULTS = {
    "agent_name": "Agent Y",
    "persona": "",  # 空 = 不额外注入；UI 可用 DEFAULT_PERSONA 预填
    "default_model": "",
    "approval_mode": None,  # None = 沿用 app 默认；显式设了才覆盖。read_only|ask|auto|full
}


class SettingsStore:
    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._data = dict(_DEFAULTS)
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                self._data.update(json.loads(self._path.read_text(encoding="utf-8")))
            except Exception:
                pass

    def _save(self) -> None:
        self._path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")

    def get(self) -> dict:
        return dict(self._data)

    def update(self, **fields) -> dict:
        for k, v in fields.items():
            if k in _DEFAULTS and v is not None:
                self._data[k] = v
        self._save()
        return self.get()

    @property
    def persona(self) -> str:
        return self._data.get("persona", "") or ""

    def effective_system(self, scenario_prompt: str) -> str:
        """人设(若设置) + 场景提示词。人设决定身份/语气，场景提供工具纪律。"""
        persona = self.persona.strip()
        return f"{persona}\n\n{scenario_prompt}" if persona else scenario_prompt
