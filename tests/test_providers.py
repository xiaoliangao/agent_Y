"""ProviderStore(keychain 抽象) + SettingsStore。key 用假后端，不碰真钥匙串。"""
from __future__ import annotations

from core.providers.store import ProviderStore
from core.settings import SettingsStore


class FakeSecrets:
    def __init__(self):
        self.d: dict[str, str] = {}

    def set(self, ref, secret):
        self.d[ref] = secret

    def get(self, ref):
        return self.d.get(ref)

    def delete(self, ref):
        self.d.pop(ref, None)


def test_provider_add_hides_key(tmp_path):
    fs = FakeSecrets()
    ps = ProviderStore(str(tmp_path / "p.db"), secrets=fs)
    c = ps.add("openai", "sk-secret", base_url="https://x", model_default="deepseek-chat")
    assert c["provider"] == "openai" and c["active"] is True  # 首个自动激活
    assert "sk-secret" not in str(c)  # 返回不含 key
    assert all("sk-secret" not in str(x) for x in ps.list())  # 列表不含 key
    assert ps.get_key(c["id"]) == "sk-secret"  # 内部可取
    assert fs.d[c["id"]] == "sk-secret"  # 进了 keychain


def test_provider_activate_and_delete_clears_keychain(tmp_path):
    fs = FakeSecrets()
    ps = ProviderStore(str(tmp_path / "p.db"), secrets=fs)
    a = ps.add("anthropic", "k1")
    b = ps.add("openai", "k2")
    assert ps.active()["id"] == a["id"]  # 首个激活
    ps.set_active(b["id"])
    assert ps.active()["id"] == b["id"]
    ps.delete(b["id"])
    assert b["id"] not in fs.d  # 删连接 → 清 keychain
    assert ps.active()["id"] == a["id"]  # 删激活项 → 自动另选


def test_settings_persona_and_effective_system(tmp_path):
    s = SettingsStore(str(tmp_path / "s.json"))
    assert s.get()["agent_name"] == "Agent Y" and s.persona == ""
    assert s.effective_system("场景提示") == "场景提示"  # 无人设 → 原样
    s.update(persona="我是私人助理")
    assert "我是私人助理" in s.effective_system("场景提示")
    assert SettingsStore(str(tmp_path / "s.json")).persona == "我是私人助理"  # 持久化
