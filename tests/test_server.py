"""FastAPI server 测试：会话 CRUD + SSE 流 + 审批暂停/恢复 + 持久化（MockProvider 驱动，离线）。

注：httpx ASGITransport 会缓冲整个响应——审批中途阻塞时拿不到流帧（真 uvicorn 无此问题）。
故审批用例用"并发任务跑流 + 经 app.state.approvals 直接解审批"的手法（等价于客户端 POST /approvals）。
"""
from __future__ import annotations

import asyncio
import json

import httpx
from httpx import ASGITransport

from core.harness.approval import ApprovalMode
from core.providers.mock import MockProvider, script_text, script_tool
from server.app import create_app


def _app(tmp_path, provider, approval_mode=ApprovalMode.AUTO):
    return create_app(
        provider=provider, db_path=str(tmp_path / "db.sqlite"),
        data_dir=str(tmp_path / "data"), approval_mode=approval_mode,
    )


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def _drain(resp) -> list[dict]:
    frames = []
    async for line in resp.aiter_lines():
        if line.startswith("data: "):
            frames.append(json.loads(line[6:]))
    return frames


async def test_session_message_sse(tmp_path):
    provider = MockProvider([
        script_tool("写文件", "write_file", {"path": "a.txt", "content": "hi"}, "t1"),
        script_text("好了"),
    ])
    async with _client(_app(tmp_path, provider, ApprovalMode.AUTO)) as client:
        sid = (await client.post("/sessions", json={"title": "t"})).json()["session_id"]
        async with client.stream("POST", f"/sessions/{sid}/messages", json={"text": "写 a.txt"}) as resp:
            assert resp.status_code == 200
            frames = await _drain(resp)
        types = [f["type"] for f in frames]
        assert "tool_use" in types and "tool_result" in types
        assert frames[-1] == {"type": "done", "reason": "completed"}
        assert (tmp_path / "data" / "sessions" / sid / "workspace" / "a.txt").read_text() == "hi"
        detail = (await client.get(f"/sessions/{sid}")).json()
        assert len(detail["messages"]) >= 3


async def test_session_persists_across_restart(tmp_path):
    async with _client(_app(tmp_path, MockProvider([script_text("hi")]))) as c1:
        sid = (await c1.post("/sessions", json={"title": "persist"})).json()["session_id"]
    app2 = create_app(provider=MockProvider([]), db_path=str(tmp_path / "db.sqlite"), data_dir=str(tmp_path / "data"))
    async with _client(app2) as c2:
        sessions = (await c2.get("/sessions")).json()["sessions"]
        assert any(s["id"] == sid and s["title"] == "persist" for s in sessions)


async def test_approval_pauses_and_resumes(tmp_path):
    provider = MockProvider([
        script_tool("写", "write_file", {"path": "x.txt", "content": "y"}, "t1"),
        script_text("done"),
    ])
    app = _app(tmp_path, provider, ApprovalMode.ASK)  # 写操作需审批
    async with _client(app) as client:
        sid = (await client.post("/sessions", json={})).json()["session_id"]

        async def consume() -> list[dict]:
            async with client.stream("POST", f"/sessions/{sid}/messages", json={"text": "写 x"}) as resp:
                return await _drain(resp)

        task = asyncio.create_task(consume())
        approved = False
        for _ in range(300):  # 等审批 future 出现并放行（等价于客户端 POST /approvals）
            if app.state.approvals:
                aid = next(iter(app.state.approvals))
                app.state.approvals[aid].set_result(True)
                approved = True
                break
            await asyncio.sleep(0.02)
        frames = await asyncio.wait_for(task, timeout=10)

        assert approved
        assert "approval_request" in [f["type"] for f in frames]
        assert frames[-1] == {"type": "done", "reason": "completed"}
        assert (tmp_path / "data" / "sessions" / sid / "workspace" / "x.txt").read_text() == "y"


async def test_post_approval_endpoint(tmp_path):
    app = _app(tmp_path, MockProvider([]))
    async with _client(app) as client:
        r = await client.post("/approvals/appr_unknown", json={"decision": "allow"})
        assert r.status_code == 409  # 不存在 → 过期
        fut = asyncio.get_running_loop().create_future()
        app.state.approvals["appr_y"] = fut
        r2 = await client.post("/approvals/appr_y", json={"decision": "allow"})
        assert r2.json()["ok"] is True
        assert fut.result() is True


async def test_404_and_error_envelope(tmp_path):
    async with _client(_app(tmp_path, MockProvider([]))) as client:
        r = await client.get("/sessions/sess_nope")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "session_not_found"


async def test_health(tmp_path):
    async with _client(_app(tmp_path, MockProvider([]))) as client:
        assert (await client.get("/health")).json()["ok"] is True


async def test_engine_wires_memory_and_context(tmp_path):
    from server.app import _build_engine

    app = _app(tmp_path, MockProvider([]))
    sid = app.state.store.create_session(title="t", scenario="coding")["id"]
    eng = _build_engine(app, sid)
    assert eng.context_manager is not None  # 压缩始终开
    assert eng.memory_store is not None and eng.reflect is True  # 记忆默认开


async def test_memory_can_be_disabled(tmp_path):
    from server.app import _build_engine

    app = create_app(
        provider=MockProvider([]), db_path=str(tmp_path / "db"),
        data_dir=str(tmp_path / "d"), memory=False,
    )
    sid = app.state.store.create_session(title="t", scenario="coding")["id"]
    eng = _build_engine(app, sid)
    assert eng.memory_store is None and eng.reflect is False
    assert eng.context_manager is not None


async def test_folders_crud(tmp_path):
    async with _client(_app(tmp_path, MockProvider([]))) as client:
        r = await client.post("/folders", json={"path": str(tmp_path / "docs")})
        assert r.status_code == 201
        fid = r.json()["id"]
        assert any(f["id"] == fid for f in (await client.get("/folders")).json()["folders"])
        assert (await client.delete(f"/folders/{fid}")).json()["ok"] is True
        assert (await client.delete(f"/folders/{fid}")).status_code == 404


async def test_todos_and_reminders_endpoints(tmp_path):
    async with _client(_app(tmp_path, MockProvider([]))) as client:
        t = (await client.post("/todos", json={"text": "买菜"})).json()
        assert t["text"] == "买菜"
        await client.patch(f"/todos/{t['id']}", json={"done": True})
        assert (await client.get("/todos")).json()["todos"][0]["done"] is True
        rem = (await client.post(
            "/reminders", json={"text": "r", "fire_at": "2030-01-01T00:00:00Z"}
        )).json()
        assert rem["text"] == "r"
        assert (await client.delete(f"/reminders/{rem['id']}")).json()["ok"] is True


async def test_assistant_scenario_selected(tmp_path):
    from server.app import _build_engine

    app = _app(tmp_path, MockProvider([]))
    app.state.fs.authorize(str(tmp_path))
    sid = app.state.store.create_session(title="a", scenario="assistant")["id"]
    eng = _build_engine(app, sid)
    names = {t.name for t in eng.tools}
    assert "read_dir" in names and "xlsx_write" in names
