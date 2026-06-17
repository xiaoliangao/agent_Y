"""文件记忆：写入/索引/召回（关键词 + picker + 小模型）+ 反思沉淀。见 design §4.5。"""
from __future__ import annotations

from core.memory.recall import humanize_age, keyword_pick
from core.memory.reflect import extract_memories
from core.memory.store import FileMemoryStore, Memory
from core.providers.mock import MockProvider, script_text
from core.types import Message, TextBlock


async def _seed(store: FileMemoryStore) -> None:
    await store.write(Memory(name="user-likes-tea", description="用户喜欢喝茶", type="user", body="喜欢绿茶"))
    await store.write(Memory(name="deploy-target", description="部署到 OCI 服务器", type="project", body="158.x"))


async def test_write_and_index(tmp_path):
    store = FileMemoryStore(str(tmp_path))
    await _seed(store)
    assert (tmp_path / "user-likes-tea.md").exists()
    idx = store.load_index()
    assert "user-likes-tea.md" in idx and "deploy-target.md" in idx
    mems = store._scan()
    assert {m.name for m in mems} == {"user-likes-tea", "deploy-target"}
    assert any(m.type == "user" for m in mems)
    assert any(m.body == "喜欢绿茶" for m in mems)


async def test_index_dedup_on_rewrite(tmp_path):
    store = FileMemoryStore(str(tmp_path))
    await store.write(Memory(name="x", description="v1", type="reference", body="a"))
    await store.write(Memory(name="x", description="v2", type="reference", body="b"))
    idx = store.load_index()
    assert idx.count("(x.md)") == 1 and "v2" in idx and "v1" not in idx


async def test_recall_keyword_fallback(tmp_path):
    store = FileMemoryStore(str(tmp_path))  # 无 provider → 关键词兜底
    await _seed(store)
    got = await store.recall("喝茶 偏好", k=5)
    assert [m.name for m in got] == ["user-likes-tea"]


async def test_recall_with_injected_picker(tmp_path):
    async def picker(query, candidates, k):
        return ["deploy-target"]

    store = FileMemoryStore(str(tmp_path), picker=picker)
    await _seed(store)
    got = await store.recall("anything")
    assert [m.name for m in got] == ["deploy-target"]
    assert got[0].body == "158.x"


async def test_recall_llm_pick(tmp_path):
    store = FileMemoryStore(
        str(tmp_path), provider=MockProvider([script_text('选: ["user-likes-tea"]')]), model="mock"
    )
    await _seed(store)
    got = await store.recall("用户偏好")
    assert [m.name for m in got] == ["user-likes-tea"]


async def test_recall_empty_when_no_memories(tmp_path):
    store = FileMemoryStore(str(tmp_path))
    assert await store.recall("x") == []


def test_humanize_age():
    now = 1_000_000.0
    assert humanize_age(now, now) == "saved today"
    assert humanize_age(now - 86400, now) == "saved 1 day ago"
    assert "47 days" in humanize_age(now - 47 * 86400, now)
    assert humanize_age(None, now) == "saved recently"


def test_keyword_pick_no_overlap_returns_empty():
    cands = [Memory(name="a", description="苹果", type="user", body="")]
    assert keyword_pick("香蕉", cands, 5) == []


async def test_reflect_writes_new_and_dedups(tmp_path):
    store = FileMemoryStore(str(tmp_path))
    await store.write(Memory(name="prefers-tea", description="old", type="user", body="old"))
    provider = MockProvider([
        script_text(
            '[{"name":"prefers-tea","description":"dup","type":"user","body":"x"},'
            '{"name":"likes-python","description":"用户偏好 Python","type":"user","body":"是"}]'
        )
    ])
    msgs = [Message(role="user", content=[TextBlock(text="我喜欢 Python")])]
    written = await extract_memories(store, provider, "mock", msgs)
    assert {m.name for m in written} == {"likes-python"}  # 重名 prefers-tea 被查重跳过
    assert (tmp_path / "likes-python.md").exists()


async def test_reflect_empty_when_no_convo(tmp_path):
    store = FileMemoryStore(str(tmp_path))
    provider = MockProvider([script_text("[]")])
    assert await extract_memories(store, provider, "mock", []) == []
