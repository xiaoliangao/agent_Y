"""FastAPI 应用：REST + SSE，仅翻译 HTTP↔SessionEngine。见 docs/design.md §4.1。

跑：`uvicorn server.app:app --host 127.0.0.1 --port 8765`
provider 由环境变量决定（AGENTY_PROVIDER=anthropic|openai、AGENTY_BASE_URL、AGENTY_MODEL、
AGENTY_KEY_ENV），测试时可注入 `create_app(provider=...)`。

审批走 SSE：写/危险操作触发 `approval_request` 帧并暂停，客户端 `POST /approvals/{id}` 恢复。
实现用 asyncio.Queue 解耦"engine 执行(后台 task)"与"SSE 拉取(响应生成器)"。
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from core.engine import SessionEngine
from core.harness.approval import ApprovalMode
from core.loop import LoopEvent
from core.sandbox.local import LocalExecutor
from core.scenarios.coding.scenario import CodingScenario
from core.store import Store
from core.types import Message, TextBlock


class SessionIn(BaseModel):
    title: str | None = None
    scenario: str | None = None


class MsgIn(BaseModel):
    text: str


class ApprovalIn(BaseModel):
    decision: str
    scope: str | None = None


def _get_provider(app: FastAPI) -> Any:
    if app.state.provider is not None:
        return app.state.provider
    prov = os.environ.get("AGENTY_PROVIDER", "anthropic")
    if prov == "openai":
        from core.providers.openai_compat import OpenAICompatProvider

        key_env = os.environ.get("AGENTY_KEY_ENV", "OPENAI_API_KEY")
        return OpenAICompatProvider(api_key=os.environ.get(key_env), base_url=os.environ.get("AGENTY_BASE_URL"))
    from core.providers.anthropic import AnthropicProvider

    return AnthropicProvider()


def _frames(ev: LoopEvent) -> list[dict]:
    """LoopEvent → SSE 事件帧（见 design §4.1.2）。"""
    out: list[dict] = []
    if ev.kind == "assistant" and ev.message is not None:
        for b in ev.message.content:
            if b.type == "text" and b.text:
                out.append({"type": "text_delta", "text": b.text})
            elif b.type == "thinking" and b.thinking:
                out.append({"type": "thinking_delta", "text": b.thinking})
            elif b.type == "tool_use":
                out.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
    elif ev.kind == "tool_results" and ev.message is not None:
        for b in ev.message.content:
            out.append({"type": "tool_result", "id": b.tool_use_id,
                        "is_error": b.is_error, "preview": str(b.content)[:500]})
    elif ev.kind == "done":
        out.append({"type": "done", "reason": ev.reason})
    return out


def _build_engine(app: FastAPI, sid: str) -> SessionEngine:
    scenario = CodingScenario()
    workspace = os.path.join(app.state.data_dir, "sessions", sid, "workspace")
    os.makedirs(workspace, exist_ok=True)
    eng = SessionEngine(
        provider=_get_provider(app), tools=scenario.tools(), system=scenario.system_prompt(),
        sandbox=LocalExecutor(workspace), model=app.state.model, approval_mode=app.state.approval_mode,
    )
    eng.messages = [Message.model_validate(m) for m in app.state.store.get_messages(sid)]
    return eng


async def _event_stream(app: FastAPI, sid: str, engine: SessionEngine, text: str):
    st = app.state
    queue: asyncio.Queue = asyncio.Queue()

    async def approve(perm) -> bool:
        approval_id = "appr_" + uuid.uuid4().hex[:10]
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        st.approvals[approval_id] = fut
        await queue.put({"type": "approval_request", "approval_id": approval_id,
                         "tool": perm.summary or "操作", "summary": perm.summary, "risk": perm.risk})
        try:
            return await fut
        finally:
            st.approvals.pop(approval_id, None)

    engine.request_approval = approve

    async def drive() -> None:
        try:
            async for ev in engine.submit(text):
                if ev.message is not None:
                    st.store.add_message(sid, ev.message.model_dump())
                for fr in _frames(ev):
                    await queue.put(fr)
        except asyncio.CancelledError:
            await queue.put({"type": "done", "reason": "aborted"})
        except Exception as e:  # noqa: BLE001
            await queue.put({"type": "error", "message": f"{type(e).__name__}: {e}"})
            await queue.put({"type": "done", "reason": "error"})
        finally:
            await queue.put(None)

    task = asyncio.create_task(drive())
    st.runs[sid] = {"task": task, "engine": engine}
    try:
        while True:
            fr = await queue.get()
            if fr is None:
                break
            yield f"data: {json.dumps(fr, ensure_ascii=False)}\n\n"
    finally:
        st.runs.pop(sid, None)
        if not task.done():
            task.cancel()
        st.store.set_status(sid, "idle")


def create_app(*, provider: Any = None, db_path: str | None = None, data_dir: str | None = None,
               model: str | None = None, approval_mode: ApprovalMode = ApprovalMode.ASK) -> FastAPI:
    app = FastAPI(title="Agent Y", version="0.1.0")
    data_dir = data_dir or ".agenty"
    app.state.store = Store(db_path or os.path.join(data_dir, "agenty.db"))
    app.state.provider = provider
    app.state.model = model or os.environ.get("AGENTY_MODEL", "claude-sonnet-4-6")
    app.state.data_dir = data_dir
    app.state.approval_mode = approval_mode
    app.state.approvals = {}   # approval_id -> Future
    app.state.runs = {}        # sid -> {task, engine}

    @app.exception_handler(HTTPException)
    async def _http_exc(_req: Request, exc: HTTPException):  # 统一错误信封（design §4.0）
        return JSONResponse(status_code=exc.status_code, content={"error": {"code": exc.detail, "message": exc.detail}})

    @app.get("/health")
    async def health():
        return {"ok": True, "service": "agent-y", "stage": "M2"}

    @app.post("/sessions", status_code=201)
    async def create_session(body: SessionIn, request: Request):
        s = request.app.state.store.create_session(title=body.title, scenario=body.scenario or "coding")
        return {"session_id": s["id"], "title": s["title"], "scenario": s["scenario"], "created_at": s["created_at"]}

    @app.get("/sessions")
    async def list_sessions(request: Request):
        return {"sessions": request.app.state.store.list_sessions()}

    @app.get("/sessions/{sid}")
    async def get_session(sid: str, request: Request):
        s = request.app.state.store.get_session(sid)
        if not s:
            raise HTTPException(404, "session_not_found")
        return {"session": s, "messages": request.app.state.store.get_messages(sid)}

    @app.post("/sessions/{sid}/messages")
    async def post_message(sid: str, body: MsgIn, request: Request):
        st = request.app.state
        if not st.store.get_session(sid):
            raise HTTPException(404, "session_not_found")
        if sid in st.runs:
            raise HTTPException(409, "session_running")
        eng = _build_engine(request.app, sid)
        st.store.add_message(sid, Message(role="user", content=[TextBlock(text=body.text)]).model_dump())
        st.store.set_status(sid, "running")
        return StreamingResponse(_event_stream(request.app, sid, eng, body.text), media_type="text/event-stream")

    @app.post("/approvals/{approval_id}")
    async def post_approval(approval_id: str, body: ApprovalIn, request: Request):
        fut = request.app.state.approvals.get(approval_id)
        if fut is None or fut.done():
            raise HTTPException(409, "approval_expired")
        fut.set_result(body.decision == "allow")
        return {"ok": True}

    @app.post("/sessions/{sid}/interrupt")
    async def interrupt(sid: str, request: Request):
        run = request.app.state.runs.get(sid)
        if run:
            run["engine"].interrupt()
        return {"ok": True}

    return app


app = create_app()  # 供 `uvicorn server.app:app` 使用
