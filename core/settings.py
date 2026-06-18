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

# 可按角色单独配模型的角色（PRD F1.4）：主力 orchestrator / 跑量 subagent / 评测 judge。
# 未配则回退到 default_model（再回退到连接默认 / app 兜底）。
ROLES = ("orchestrator", "subagent", "judge")

_DEFAULTS = {
    "agent_name": "Agent Y",
    "persona": "",  # 空 = 不额外注入；UI 可用 DEFAULT_PERSONA 预填
    "default_model": "",
    "models": {},  # 按角色配模型：{"orchestrator":..,"subagent":..,"judge":..}；空=用 default_model（F1.4）
    "approval_mode": None,  # None = 沿用 app 默认；显式设了才覆盖。read_only|ask|auto|full
    "sandbox": "local",  # local（宿主机跑，开发友好）| docker（容器隔离，需装 Docker）
    # 网络代理（web_search/web_fetch/天气 等外联走它）：auto=自动读系统代理 / 留空=不用 / 或 http://127.0.0.1:7897
    "proxy": "auto",
    # 日常面板天气（手动城市，隐私优先；lat/lon/label 为 geocode 后的缓存，UI 不直接编辑）
    "weather_city": "",
    "weather_lat": None,
    "weather_lon": None,
    "weather_label": "",
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
        # 改了城市 → 作废 geocode 缓存（下次 /weather 重新解析）
        if "weather_city" in fields and (fields.get("weather_city") or "") != self._data.get("weather_city"):
            self._data.update(weather_lat=None, weather_lon=None, weather_label="")
        for k, v in fields.items():
            if k not in _DEFAULTS or v is None:
                continue
            if k == "models" and isinstance(v, dict):
                self._data["models"] = self._clean_models(v)  # 整体替换（UI 传完整 models 对象）
            else:
                self._data[k] = v
        self._save()
        return self.get()

    @staticmethod
    def _clean_models(m: dict) -> dict:
        """只留已知角色、去掉空值（空=回退到 default_model）。"""
        return {r: str(m[r]).strip() for r in ROLES if (m.get(r) or "").strip()}

    @property
    def persona(self) -> str:
        return self._data.get("persona", "") or ""

    def model_for(self, role: str) -> str:
        """该角色单独配置的模型 id；未配则返回空串（调用方回退到 default_model）。见 PRD F1.4。"""
        return ((self._data.get("models") or {}).get(role) or "").strip()

    def effective_system(self, scenario_prompt: str) -> str:
        """人设(若设置) + 场景提示词。人设决定身份/语气，场景提供工具纪律。"""
        persona = self.persona.strip()
        return f"{persona}\n\n{scenario_prompt}" if persona else scenario_prompt
