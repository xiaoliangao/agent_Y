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


async def test_file_change_frame_and_revert(tmp_path):
    provider = MockProvider([
        script_tool("写", "write_file", {"path": "hello.py", "content": "print(1)\n"}, "t1"),
        script_text("done"),
    ])
    async with _client(_app(tmp_path, provider, ApprovalMode.AUTO)) as client:
        sid = (await client.post("/sessions", json={"scenario": "coding"})).json()["session_id"]
        async with client.stream("POST", f"/sessions/{sid}/messages", json={"text": "写 hello.py"}) as resp:
            frames = await _drain(resp)
        fc = [f for f in frames if f["type"] == "file_change"]
        assert len(fc) == 1 and fc[0]["path"] == "hello.py" and "+print(1)" in fc[0]["diff"]
        # 撤销：写回原内容（空）
        assert (await client.post(f"/sessions/{sid}/revert", json={"path": "hello.py", "content": ""})).json()["ok"]
        ws = tmp_path / "data" / "sessions" / sid / "workspace"
        assert (ws / "hello.py").read_text() == ""
        # 越界拒绝
        bad = await client.post(f"/sessions/{sid}/revert", json={"path": "../escape.txt", "content": "x"})
        assert bad.status_code == 400


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


async def test_automations_and_review_endpoints(tmp_path):
    provider = MockProvider([script_text("自动化产出内容")])
    async with _client(_app(tmp_path, provider, ApprovalMode.AUTO)) as client:
        a = (await client.post(
            "/automations", json={"name": "日报", "schedule": "daily@08:00", "prompt": "写日报"}
        )).json()
        assert a["enabled"] is True
        assert len((await client.get("/automations")).json()["automations"]) == 1
        # 手动触发 → 跑 agent(mock) → 进 review 队列
        rev = (await client.post(f"/automations/{a['id']}/run")).json()
        assert "自动化产出内容" in rev["output"] and rev["status"] == "pending"
        assert len((await client.get("/review-queue")).json()["reviews"]) == 1
        decided = (await client.post(f"/review-queue/{rev['id']}", json={"decision": "accept"})).json()
        assert decided["status"] == "accepted"
        await client.patch(f"/automations/{a['id']}", json={"enabled": False})
        assert (await client.get("/automations")).json()["automations"][0]["enabled"] is False
        assert (await client.delete(f"/automations/{a['id']}")).json()["ok"] is True


async def test_sandbox_setting_selects_executor(tmp_path):
    from core.sandbox.docker import DockerSandbox
    from core.sandbox.local import LocalExecutor
    from server.app import _sandbox

    app = _app(tmp_path, MockProvider([]))
    assert isinstance(_sandbox(app, str(tmp_path)), LocalExecutor)  # 默认 local
    app.state.settings.update(sandbox="docker")
    assert isinstance(_sandbox(app, str(tmp_path)), DockerSandbox)  # 切 docker（惰性，不连 daemon）


async def test_assistant_scenario_selected(tmp_path):
    from server.app import _build_engine

    app = _app(tmp_path, MockProvider([]))
    app.state.fs.authorize(str(tmp_path))
    sid = app.state.store.create_session(title="a", scenario="assistant")["id"]
    eng = _build_engine(app, sid)
    names = {t.name for t in eng.tools}
    assert "read_dir" in names and "xlsx_write" in names


async def test_providers_models_settings_endpoints(tmp_path):
    from tests.test_providers import FakeSecrets

    app = create_app(
        provider=MockProvider([]), db_path=str(tmp_path / "db"),
        data_dir=str(tmp_path / "d"), provider_secrets=FakeSecrets(),
    )
    async with _client(app) as client:
        r = await client.post(
            "/providers", json={"provider": "openai", "api_key": "sk-x", "model_default": "deepseek-chat"}
        )
        assert r.status_code == 201 and "sk-x" not in r.text  # 响应不回显 key
        cid = r.json()["id"]
        conns = (await client.get("/providers")).json()["connections"]
        assert conns[0]["active"] is True and "sk-x" not in str(conns)
        assert (await client.get("/models")).json()["models"]
        assert (await client.get("/settings")).json()["persona_suggestion"]  # 默认人设建议
        await client.put("/settings", json={"persona": "私人助理", "default_model": "deepseek-chat"})
        assert (await client.get("/settings")).json()["settings"]["persona"] == "私人助理"
        assert (await client.delete(f"/providers/{cid}")).json()["ok"] is True


async def test_workspace_files_list_and_read(tmp_path):
    app = _app(tmp_path, MockProvider([script_text("ok")]))
    async with _client(app) as client:
        sid = (await client.post("/sessions", json={"scenario": "coding"})).json()["session_id"]
        ws = tmp_path / "data" / "sessions" / sid / "workspace"
        (ws / "sub").mkdir(parents=True)
        (ws / "a.py").write_text("print(1)\n")
        (ws / "sub" / "b.txt").write_text("hi")
        paths = [f["path"] for f in (await client.get(f"/sessions/{sid}/files")).json()["files"]]
        assert "a.py" in paths and "sub/b.txt" in paths
        r = (await client.get(f"/sessions/{sid}/file", params={"path": "a.py"})).json()
        assert r["content"] == "print(1)\n" and r["truncated"] is False
        assert (await client.get(f"/sessions/{sid}/file", params={"path": "../../../etc/hosts"})).status_code == 400
        assert (await client.get(f"/sessions/{sid}/file", params={"path": "nope.py"})).status_code == 404


async def test_open_folder_and_new_file(tmp_path):
    app = _app(tmp_path, MockProvider([script_text("ok")]))
    proj = tmp_path / "myproj"
    (proj / "src").mkdir(parents=True)
    (proj / "src" / "main.py").write_text("print('hi')\n")
    async with _client(app) as client:
        sid = (await client.post("/sessions", json={"scenario": "coding"})).json()["session_id"]
        r = (await client.post(f"/sessions/{sid}/workspace", json={"path": str(proj)})).json()
        assert r["is_custom"] and r["name"] == "myproj"
        d = (await client.get(f"/sessions/{sid}/files")).json()
        assert d["is_custom"] and "src/main.py" in [f["path"] for f in d["files"]]
        nf = await client.post(f"/sessions/{sid}/new-file", json={"path": "notes/todo.md", "content": "# hi"})
        assert nf.status_code == 201 and nf.json()["path"] == "notes/todo.md"
        assert (proj / "notes" / "todo.md").read_text() == "# hi"
        assert (await client.post(f"/sessions/{sid}/new-file", json={"path": "notes/todo.md"})).status_code == 409
        assert (await client.post(f"/sessions/{sid}/workspace", json={"path": str(tmp_path / "nope")})).status_code == 400
        assert (await client.delete(f"/sessions/{sid}/workspace")).json()["ok"]
        assert (await client.get(f"/sessions/{sid}/files")).json()["is_custom"] is False


async def test_skills_crud(tmp_path):
    app = _app(tmp_path, MockProvider([]))
    async with _client(app) as client:
        assert (await client.get("/skills")).json()["skills"] == []
        r = await client.post("/skills", json={"name": "周报", "description": "写周报", "when_to_use": "周五", "body": "按要点写"})
        assert r.status_code == 201 and r.json()["name"] == "周报"
        assert any(s["name"] == "周报" for s in (await client.get("/skills")).json()["skills"])
        assert (await client.get("/skills/周报")).json()["body"] == "按要点写"
        assert (await client.delete("/skills/周报")).json()["ok"]
        assert (await client.get("/skills")).json()["skills"] == []


async def test_skill_install_endpoint(tmp_path):
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    (pkg / "SKILL.md").write_text("---\nname: 翻译\ndescription: 中英互译\n---\n\n保持术语一致")
    (pkg / "glossary.txt").write_text("term=术语")
    app = _app(tmp_path, MockProvider([]))
    async with _client(app) as client:
        r = await client.post("/skills/install", json={"path": str(pkg)})
        assert r.status_code == 201 and r.json()["name"] == "翻译" and "glossary.txt" in r.json()["files"]
        assert any(s["name"] == "翻译" for s in (await client.get("/skills")).json()["skills"])
        assert (await client.post("/skills/install", json={"path": str(tmp_path / "nope")})).status_code == 400


async def test_delete_session(tmp_path):
    app = _app(tmp_path, MockProvider([]))
    async with _client(app) as client:
        sid = (await client.post("/sessions", json={"title": "t"})).json()["session_id"]
        assert any(s["id"] == sid for s in (await client.get("/sessions")).json()["sessions"])
        assert (await client.delete(f"/sessions/{sid}")).json()["ok"]
        assert (await client.get(f"/sessions/{sid}")).status_code == 404
        assert all(s["id"] != sid for s in (await client.get("/sessions")).json()["sessions"])
        assert (await client.delete("/sessions/nope")).status_code == 404


async def test_serves_frontend_when_present(tmp_path):
    fe = tmp_path / "fe"
    fe.mkdir()
    (fe / "index.html").write_text("<h1>Agent Y</h1>")
    app = create_app(
        provider=MockProvider([]), db_path=str(tmp_path / "db"),
        data_dir=str(tmp_path / "d"), frontend_dir=str(fe),
    )
    async with _client(app) as client:
        assert "Agent Y" in (await client.get("/")).text  # 前端首页
        assert (await client.get("/health")).json()["ok"] is True  # API 仍工作
