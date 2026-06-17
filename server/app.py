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
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from core.engine import SessionEngine
from core.harness.approval import ApprovalMode
from core.harness.fs_access import FolderAccess
from core.loop import LoopEvent
from core.sandbox.local import LocalExecutor
from core.scenarios.assistant.scenario import AssistantScenario
from core.scenarios.coding.scenario import CodingScenario
from core.scheduler.store import SchedulerStore
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


class FolderIn(BaseModel):
    path: str
    mode: str | None = None


class TodoIn(BaseModel):
    text: str
    due: str | None = None


class TodoPatch(BaseModel):
    done: bool | None = None
    text: str | None = None
    due: str | None = None


class ReminderIn(BaseModel):
    text: str
    fire_at: str
    todo_id: str | None = None
    repeat: str | None = None


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
    """LoopEvent → SSE 事件帧（见 design §4.1.2）。token 级：text_delta 来自 live delta。

    'assistant' 事件不产帧（文本已逐字流过，避免重复），但 drive() 仍据其 message 持久化。
    """
    if ev.kind == "text_delta" and ev.text:
        return [{"type": "text_delta", "text": ev.text}]
    if ev.kind == "thinking_delta" and ev.text:
        return [{"type": "thinking_delta", "text": ev.text}]
    if ev.kind == "tool_use" and ev.tool_use is not None:
        return [{"type": "tool_use", "id": ev.tool_use.id, "name": ev.tool_use.name, "input": ev.tool_use.input}]
    if ev.kind == "tool_results" and ev.message is not None:
        return [{"type": "tool_result", "id": b.tool_use_id, "is_error": b.is_error,
                 "preview": str(b.content)[:500]} for b in ev.message.content]
    if ev.kind == "done":
        return [{"type": "done", "reason": ev.reason}]
    return []


def _build_engine(app: FastAPI, sid: str) -> SessionEngine:
    sess = app.state.store.get_session(sid)
    if sess and sess.get("scenario") == "assistant":
        scenario: Any = AssistantScenario(app.state.fs)
    else:
        scenario = CodingScenario()
    workspace = os.path.join(app.state.data_dir, "sessions", sid, "workspace")
    os.makedirs(workspace, exist_ok=True)
    provider = _get_provider(app)
    # 上下文压缩（始终开，便宜）+ 长期记忆（按 app.state.memory_enabled，跨会话共享）
    from core.harness.context import ContextManager, context_window_for

    context_manager = ContextManager(
        provider=provider, model=app.state.model, context_window=context_window_for(app.state.model)
    )
    memory_store = None
    if app.state.memory_enabled:
        from core.memory.store import FileMemoryStore

        memory_store = FileMemoryStore(
            os.path.join(app.state.data_dir, "memory"), provider=provider, model=app.state.model
        )
    from core.obs.tracer import build_tracer

    eng = SessionEngine(
        provider=provider, tools=scenario.tools(), system=scenario.system_prompt(),
        sandbox=LocalExecutor(workspace), model=app.state.model, approval_mode=app.state.approval_mode,
        tracer=build_tracer(console=False), context_manager=context_manager,
        memory_store=memory_store, reflect=memory_store is not None,
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


def _default_frontend() -> str:
    import sys

    if getattr(sys, "frozen", False):  # PyInstaller 打包后：dist 随包(sys._MEIPASS/frontend)
        return os.path.join(sys._MEIPASS, "frontend")  # type: ignore[attr-defined]
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "agent-y", "dist")


def create_app(*, provider: Any = None, db_path: str | None = None, data_dir: str | None = None,
               model: str | None = None, approval_mode: ApprovalMode = ApprovalMode.ASK,
               memory: bool | None = None, frontend_dir: str | None = None) -> FastAPI:
    app = FastAPI(title="Agent Y", version="0.1.0")
    # 本地单用户：放开 CORS，便于前端 dev server(另一端口) 直连。生产同源(pywebview)时无所谓。
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
    )
    # 默认绝对路径（~/.agenty）：打包后 Finder 启动 cwd=/，相对 ".agenty" 会落到只读的 /.agenty
    data_dir = data_dir or os.environ.get("AGENTY_DATA") or os.path.expanduser("~/.agenty")
    app.state.store = Store(db_path or os.path.join(data_dir, "agenty.db"))
    app.state.provider = provider
    app.state.model = model or os.environ.get("AGENTY_MODEL", "claude-sonnet-4-6")
    app.state.data_dir = data_dir
    app.state.approval_mode = approval_mode
    app.state.memory_enabled = (
        memory if memory is not None else os.environ.get("AGENTY_MEMORY", "on") != "off"
    )
    app.state.approvals = {}   # approval_id -> Future
    app.state.runs = {}        # sid -> {task, engine}
    app.state.fs = FolderAccess(os.path.join(data_dir, "folders.json"))  # 助手文件夹授权
    app.state.scheduler = SchedulerStore(os.path.join(data_dir, "scheduler.db"))  # 待办/提醒

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

    # ---------- 个人助手：文件夹授权 / 待办 / 提醒（M5）----------
    @app.get("/folders")
    async def list_folders(request: Request):
        return {"folders": request.app.state.fs.list()}

    @app.post("/folders", status_code=201)
    async def add_folder(body: FolderIn, request: Request):
        return request.app.state.fs.authorize(body.path, mode=body.mode or "read_write")

    @app.delete("/folders/{fid}")
    async def del_folder(fid: str, request: Request):
        if not request.app.state.fs.revoke(fid):
            raise HTTPException(404, "folder_not_found")
        return {"ok": True}

    @app.get("/todos")
    async def list_todos(request: Request):
        return {"todos": request.app.state.scheduler.list_todos()}

    @app.post("/todos", status_code=201)
    async def add_todo(body: TodoIn, request: Request):
        return request.app.state.scheduler.add_todo(body.text, due=body.due)

    @app.patch("/todos/{tid}")
    async def patch_todo(tid: str, body: TodoPatch, request: Request):
        t = request.app.state.scheduler.update_todo(tid, done=body.done, text=body.text, due=body.due)
        if t is None:
            raise HTTPException(404, "todo_not_found")
        return t

    @app.delete("/todos/{tid}")
    async def del_todo(tid: str, request: Request):
        if not request.app.state.scheduler.delete_todo(tid):
            raise HTTPException(404, "todo_not_found")
        return {"ok": True}

    @app.get("/reminders")
    async def list_reminders(request: Request):
        return {"reminders": request.app.state.scheduler.list_reminders()}

    @app.post("/reminders", status_code=201)
    async def add_reminder(body: ReminderIn, request: Request):
        return request.app.state.scheduler.add_reminder(
            body.text, body.fire_at, todo_id=body.todo_id, repeat=body.repeat
        )

    @app.delete("/reminders/{rid}")
    async def del_reminder(rid: str, request: Request):
        if not request.app.state.scheduler.delete_reminder(rid):
            raise HTTPException(404, "reminder_not_found")
        return {"ok": True}

    # 末尾挂载前端静态产物（若存在）：打包后桌面窗口直接 http://127.0.0.1:port/ 同源访问。
    # 必须在所有 API 路由之后挂载，"/" 兜底不抢 API。
    frontend = frontend_dir or os.environ.get("AGENTY_FRONTEND") or _default_frontend()
    if frontend and os.path.isdir(frontend):
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")

    return app


def _env_approval() -> ApprovalMode:
    return ApprovalMode.AUTO if os.environ.get("AGENTY_APPROVAL", "ask") == "auto" else ApprovalMode.ASK


app = create_app(approval_mode=_env_approval())  # 供 `uvicorn server.app:app` 使用

