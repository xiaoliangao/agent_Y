"""静态模型目录（能力声明）。见 PRD F1.3。

给 UI 列模型 + 标能力；Runtime 据能力优雅降级（如非 Claude 不发 thinking）。
价格 = 美元/百万 token（in/out）。可随模型更新增删。
"""
from __future__ import annotations

MODELS: list[dict] = [
    # Anthropic 原生
    {"id": "claude-opus-4-8", "provider": "anthropic", "label": "Claude Opus 4.8",
     "context_window": 1_000_000, "supports_tools": True, "supports_thinking": True,
     "price_in": 5, "price_out": 25},
    {"id": "claude-sonnet-4-6", "provider": "anthropic", "label": "Claude Sonnet 4.6",
     "context_window": 1_000_000, "supports_tools": True, "supports_thinking": True,
     "price_in": 3, "price_out": 15},
    {"id": "claude-haiku-4-5", "provider": "anthropic", "label": "Claude Haiku 4.5",
     "context_window": 200_000, "supports_tools": True, "supports_thinking": True,
     "price_in": 1, "price_out": 5},
    # OpenAI 兼容端点（DeepSeek / GPT / 本地等，填 base_url）
    {"id": "deepseek-chat", "provider": "openai", "label": "DeepSeek Chat",
     "context_window": 64_000, "supports_tools": True, "supports_thinking": False,
     "price_in": 0.27, "price_out": 1.1},
    {"id": "deepseek-reasoner", "provider": "openai", "label": "DeepSeek Reasoner",
     "context_window": 64_000, "supports_tools": True, "supports_thinking": True,
     "price_in": 0.55, "price_out": 2.2},
    {"id": "gpt-4o", "provider": "openai", "label": "GPT-4o",
     "context_window": 128_000, "supports_tools": True, "supports_thinking": False,
     "price_in": 2.5, "price_out": 10},
]


def models_for(provider: str | None = None) -> list[dict]:
    if provider is None:
        return list(MODELS)
    return [m for m in MODELS if m["provider"] == provider]
