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
from core.providers.catalog import MODELS
from core.providers.store import ProviderStore
from core.sandbox.local import LocalExecutor
from core.sandbox.recording import RecordingSandbox
from core.scenarios.assistant.scenario import AssistantScenario
from core.scenarios.coding.scenario import CodingScenario
from core.scheduler.automations import check_and_run
from core.scheduler.store import SchedulerStore
from core.settings import DEFAULT_PERSONA, SettingsStore
from core.store import Store
from core.types import Message, TextBlock

_APPROVAL = {"read_only": ApprovalMode.READ_ONLY, "ask": ApprovalMode.ASK,
             "auto": ApprovalMode.AUTO, "full": ApprovalMode.FULL}


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


class ProviderIn(BaseModel):
    provider: str  # anthropic | openai
    api_key: str
    base_url: str | None = None
    model_default: str | None = None


class SettingsIn(BaseModel):
    agent_name: str | None = None
    persona: str | None = None
    default_model: str | None = None
    models: dict[str, str] | None = None  # 按角色配模型 {orchestrator|subagent|judge: model_id}（F1.4）
    approval_mode: str | None = None
    sandbox: str | None = None  # local | docker
    weather_city: str | None = None  # 日常面板天气城市（手动）
    proxy: str | None = None  # 网络代理：auto / 空 / http://host:port


class AutomationIn(BaseModel):
    name: str
    schedule: str  # daily@HH:MM | Nm | Nh
    prompt: str
    scenario: str | None = None


class AutomationPatch(BaseModel):
    name: str | None = None
    schedule: str | None = None
    prompt: str | None = None
    scenario: str | None = None
    enabled: bool | None = None


class DecisionIn(BaseModel):
    decision: str  # accept | discard


class RevertIn(BaseModel):
    path: str
    content: str


class WorkspaceIn(BaseModel):
    path: str  # 打开一个文件夹作为该会话的工作区（IDE「打开文件夹」）


class NewFileIn(BaseModel):
    path: str            # 相对工作区的新文件路径
    content: str | None = None


class SkillIn(BaseModel):
    name: str
    description: str | None = None
    when_to_use: str | None = None
    body: str | None = None


class SkillInstallIn(BaseModel):
    path: str  # 含 SKILL.md 的技能文件夹（或 SKILL.md 文件）路径


def _get_provider(app: FastAPI) -> Any:
    if app.state.provider is not None:
        return app.state.provider  # 测试注入
    conn = app.state.providers.active()  # 用户在设置页配的激活连接（key 在 keychain）
    if conn:
        key = app.state.providers.get_key(conn["id"])
        if conn["provider"] == "openai":
            from core.providers.openai_compat import OpenAICompatProvider

            return OpenAICompatProvider(api_key=key, base_url=conn["base_url"])
        from core.providers.anthropic import AnthropicProvider

        return AnthropicProvider(api_key=key)
    # 兜底：环境变量（向后兼容 / 无连接时）
    prov = os.environ.get("AGENTY_PROVIDER", "anthropic")
    if prov == "openai":
        from core.providers.openai_compat import OpenAICompatProvider

        key_env = os.environ.get("AGENTY_KEY_ENV", "OPENAI_API_KEY")
        return OpenAICompatProvider(api_key=os.environ.get(key_env), base_url=os.environ.get("AGENTY_BASE_URL"))
    from core.providers.anthropic import AnthropicProvider

    return AnthropicProvider()


def _active_model(app: FastAPI, role: str = "orchestrator") -> str:
    """某角色的有效模型（PRD F1.4）。

    优先级：设置页该角色配模型 → default_model → 激活连接 model_default → app.state.model。
    role ∈ {orchestrator(主力/会话主 loop)、subagent(子 agent)、judge(eval 评测)}。
    """
    s = app.state.settings
    role_model = s.model_for(role)
    if role_model:
        return role_model
    data = s.get()
    if data.get("default_model"):
        return data["default_model"]
    conn = app.state.providers.active()
    if conn and conn.get("model_default"):
        return conn["model_default"]
    return app.state.model


def _resolve_proxy(value: str) -> str:
    """代理设置 → 实际代理 URL。auto=读系统/环境代理；留空=不用；否则原样。"""
    v = (value or "").strip()
    if not v:
        return ""
    if v.lower() == "auto":
        import urllib.request

        p = urllib.request.getproxies()  # macOS 会读系统网络代理（打包后也能读到）
        return p.get("https") or p.get("http") or ""
    return v


def _apply_proxy(app: FastAPI) -> None:
    """把代理设置落到进程环境变量：httpx(trust_env) 的外联请求即走代理；回环始终绕过。"""
    proxy = _resolve_proxy(app.state.settings.get().get("proxy", ""))
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        if proxy:
            os.environ[k] = proxy
        else:
            os.environ.pop(k, None)
    for k in ("NO_PROXY", "no_proxy"):  # 自连后端/健康检查不走代理
        if "127.0.0.1" not in os.environ.get(k, ""):
            os.environ[k] = (os.environ.get(k, "") + ",127.0.0.1,localhost,::1").lstrip(",")


_WEEK = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _runtime_preamble(app: FastAPI, model: str) -> str:
    """运行信息：真实模型 + 当前本地时间 + 诚实约束。解决「乱报模型/没有实时时间」。"""
    import datetime

    now = datetime.datetime.now().astimezone()
    conn = app.state.providers.active()
    via = f"（{conn['provider']} 接入）" if conn and conn.get("provider") else ""
    return (
        f"系统信息：你是 Agent Y 个人助手，背后由用户在设置里配置的模型「{model}」{via}驱动。"
        f"当前本地时间：{now:%Y-%m-%d %H:%M} {_WEEK[now.weekday()]}。"
        "被问「你是什么模型」时如实回答上面这个模型 id，切勿冒充 Claude/GPT 等其它厂商模型；"
        "需要当前日期/时间直接用上面的；天气、新闻、实时赛事等外部信息要用工具查询、不要臆造。"
    )


def _sandbox(app: FastAPI, ws: str) -> Any:
    """按设置选执行器：docker（容器隔离，需装 Docker）或 local（宿主机，开发友好）。"""
    if app.state.settings.get().get("sandbox") == "docker":
        from core.sandbox.docker import DockerSandbox

        return DockerSandbox()
    return LocalExecutor(ws)


# IDE「打开文件夹」：会话可指定一个真实目录作工作区；否则用默认的 per-session workspace。
_WS_SKIP = {".git", "__pycache__", "node_modules", "dist", "build", ".venv", "venv",
            ".next", "target", ".idea", ".vscode", ".pytest_cache", ".ruff_cache", ".mypy_cache"}


def _session_ws(app: FastAPI, sid: str) -> str:
    custom = (getattr(app.state, "workspaces", None) or {}).get(sid)
    if custom and os.path.isdir(custom):
        return os.path.realpath(custom)
    ws = os.path.join(app.state.data_dir, "sessions", sid, "workspace")
    os.makedirs(ws, exist_ok=True)
    return os.path.realpath(ws)


def _save_workspaces(app: FastAPI) -> None:
    with open(os.path.join(app.state.data_dir, "workspaces.json"), "w", encoding="utf-8") as f:
        json.dump(app.state.workspaces, f, ensure_ascii=False)


async def _run_automation(app: FastAPI, prompt: str, scenario_name: str) -> str:
    """自动化跑一次 agent（无会话、自动审批），收集助手文本作为产出。"""
    from core.obs.tracer import build_tracer

    scenario: Any = AssistantScenario(app.state.fs) if scenario_name == "assistant" else CodingScenario()
    ws = os.path.join(app.state.data_dir, "automations_ws")
    os.makedirs(ws, exist_ok=True)
    model = _active_model(app)
    tools = list(scenario.tools())
    if scenario_name == "assistant":
        from core.tools.todo import AddReminderTool, AddTodoTool

        tools += [AddTodoTool(app.state.scheduler), AddReminderTool(app.state.scheduler)]
    eng = SessionEngine(
        provider=_get_provider(app), tools=tools,
        system=_runtime_preamble(app, model) + "\n\n" + app.state.settings.effective_system(scenario.system_prompt()),
        sandbox=_sandbox(app, ws), model=model,
        approval_mode=ApprovalMode.AUTO, tracer=build_tracer(console=False),
    )
    parts: list[str] = []
    async for ev in eng.submit(prompt):
        if ev.kind == "text_delta" and ev.text:
            parts.append(ev.text)
    return "".join(parts).strip() or "(无输出)"


async def _scheduler_loop(app: FastAPI) -> None:
    interval = getattr(app.state, "scheduler_interval", 60)
    while True:
        await asyncio.sleep(interval)
        try:
            await check_and_run(app.state.scheduler, lambda p, s: _run_automation(app, p, s))
        except Exception:  # noqa: BLE001
            pass


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


def _file_change_frames(sandbox: Any) -> list[dict]:
    """RecordingSandbox 的改动 → file_change 帧（path + unified diff + old，供前端审阅/撤销）。"""
    import difflib

    out: list[dict] = []
    for path, ch in getattr(sandbox, "changes", {}).items():
        if ch["old"] == ch["new"]:
            continue
        diff = "\n".join(difflib.unified_diff(
            ch["old"].splitlines(), ch["new"].splitlines(),
            fromfile=path, tofile=path, lineterm="", n=3,
        ))
        out.append({"type": "file_change", "path": path, "diff": diff, "old": ch["old"]})
    return out


def _build_engine(app: FastAPI, sid: str) -> SessionEngine:
    sess = app.state.store.get_session(sid)
    if sess and sess.get("scenario") == "assistant":
        scenario: Any = AssistantScenario(app.state.fs)
    else:
        scenario = CodingScenario()
    workspace = _session_ws(app, sid)  # 默认 per-session，或用户「打开文件夹」指定的真实目录
    provider = _get_provider(app)
    model = _active_model(app, "orchestrator")  # 会话主 loop（F1.4）
    sub_model = _active_model(app, "subagent")  # 子 agent 可配更便宜的跑量模型
    settings = app.state.settings.get()
    system = _runtime_preamble(app, model) + "\n\n" + app.state.settings.effective_system(scenario.system_prompt())
    if getattr(scenario, "name", "") == "assistant":  # 把已授权目录告诉模型，否则它不知道自己能访问哪
        folders = app.state.fs.list()
        if folders:
            system += "\n\n# 已授权目录（你可以直接在这些目录里读 / 搜 / 写文件、生成办公文档，无需再让用户授权）\n" + \
                "\n".join(f"- {f['path']}（{f.get('mode', 'read_write')}）" for f in folders)
        else:
            system += "\n\n（当前没有已授权目录。需要读写本地文件时，提示用户点输入框的 📎 选择一个文件夹授权。）"
    approval = _APPROVAL.get(settings.get("approval_mode", ""), app.state.approval_mode)
    # 上下文压缩（始终开，便宜）+ 长期记忆（按 app.state.memory_enabled，跨会话共享）
    from core.harness.context import ContextManager, context_window_for

    context_manager = ContextManager(
        provider=provider, model=model, context_window=context_window_for(model)
    )
    memory_store = None
    if app.state.memory_enabled:
        from core.memory.store import FileMemoryStore

        memory_store = FileMemoryStore(
            os.path.join(app.state.data_dir, "memory"), provider=provider, model=model
        )
    from core.obs.tracer import build_tracer
    from core.tools.skill import UseSkillTool
    from core.tools.subagent import SpawnAgentTool

    base_tools = scenario.tools() + [UseSkillTool(app.state.skills)]  # 技能渐进披露
    if getattr(scenario, "name", "") == "assistant":  # 助手能把日程写进待办/提醒
        from core.tools.todo import AddReminderTool, AddTodoTool

        base_tools += [AddTodoTool(app.state.scheduler), AddReminderTool(app.state.scheduler)]
    # 每个会话带 spawn_agent（子 agent 用同一组工具但不含 spawn 自身，防递归）；子 agent 走 subagent 角色模型
    tools = base_tools + [SpawnAgentTool(provider=provider, model=sub_model, tools=base_tools, system=system)]
    eng = SessionEngine(
        provider=provider, tools=tools, system=system,
        sandbox=RecordingSandbox(_sandbox(app, workspace)),  # 记录文件改动供 diff 审阅
        model=model, approval_mode=approval,
        tracer=build_tracer(console=False), context_manager=context_manager,
        memory_store=memory_store, reflect=memory_store is not None,
        skill_store=app.state.skills,
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
                if ev.kind == "done":  # 收尾前先推文件改动 diff
                    for fr in _file_change_frames(engine.sandbox):
                        await queue.put(fr)
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
               memory: bool | None = None, frontend_dir: str | None = None,
               provider_secrets: Any = None, run_scheduler: bool = False) -> FastAPI:
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
    app.state.providers = ProviderStore(  # BYOK 连接（key 进 keychain）
        os.path.join(data_dir, "providers.db"), secrets=provider_secrets
    )
    app.state.settings = SettingsStore(os.path.join(data_dir, "settings.json"))  # 人设/默认模型/审批
    app.state.workspaces = {}  # sid -> 打开的文件夹路径（IDE「打开文件夹」）；持久化到 workspaces.json
    try:
        with open(os.path.join(data_dir, "workspaces.json"), encoding="utf-8") as f:
            app.state.workspaces = json.load(f)
    except Exception:
        pass
    from core.skills.store import FileSkillStore

    app.state.skills = FileSkillStore(os.path.join(data_dir, "skills"))  # 用户导入的技能（渐进披露）
    _apply_proxy(app)  # 按设置的代理落进程环境（外联走代理；打包后 Finder 启动不继承 shell 代理时尤其需要）

    @app.exception_handler(HTTPException)
    async def _http_exc(_req: Request, exc: HTTPException):  # 统一错误信封（design §4.0）
        return JSONResponse(status_code=exc.status_code, content={"error": {"code": exc.detail, "message": exc.detail}})

    if run_scheduler:  # 后台定时调度（桌面/真服开；测试默认关，避免无限循环）
        @app.on_event("startup")
        async def _start_scheduler():
            app.state._sched_task = asyncio.create_task(_scheduler_loop(app))

        @app.on_event("shutdown")
        async def _stop_scheduler():
            task = getattr(app.state, "_sched_task", None)
            if task:
                task.cancel()

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

    @app.patch("/sessions/{sid}")
    async def rename_session(sid: str, body: SessionIn, request: Request):  # 重命名会话
        if not (body.title or "").strip():
            raise HTTPException(400, "empty_title")
        if not request.app.state.store.rename_session(sid, body.title.strip()):
            raise HTTPException(404, "session_not_found")
        return {"ok": True, "title": body.title.strip()}

    @app.delete("/sessions/{sid}")
    async def delete_session(sid: str, request: Request):
        st = request.app.state
        run = st.runs.get(sid)
        if run:  # 正在跑的先中断
            run["engine"].interrupt()
        if not st.store.delete_session(sid):
            raise HTTPException(404, "session_not_found")
        # 清掉「打开的文件夹」记录（只去映射，不删用户真实项目目录）+ 本会话自己的工作区目录
        if st.workspaces.pop(sid, None) is not None:
            _save_workspaces(request.app)
        import shutil

        shutil.rmtree(os.path.join(st.data_dir, "sessions", sid), ignore_errors=True)
        return {"ok": True}

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

    @app.post("/sessions/{sid}/revert")
    async def revert_file(sid: str, body: RevertIn, request: Request):  # diff 审阅「撤销」：写回原内容
        ws = _session_ws(request.app, sid)
        target = os.path.realpath(os.path.join(ws, body.path))
        if target != ws and not target.startswith(ws + os.sep):
            raise HTTPException(400, "bad_path")  # 防越界
        os.makedirs(os.path.dirname(target) or ws, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(body.content)
        return {"ok": True}

    @app.get("/sessions/{sid}/files")
    async def list_workspace_files(sid: str, request: Request):  # 编码 IDE：工作区文件树（只读）
        ws = _session_ws(request.app, sid)
        custom = (request.app.state.workspaces or {}).get(sid)
        out: list[dict] = []
        if os.path.isdir(ws):
            for root, dirs, fns in os.walk(ws):
                dirs[:] = [d for d in dirs if not d.startswith(".") and d not in _WS_SKIP]
                for fn in fns:
                    if fn.startswith("."):
                        continue
                    full = os.path.join(root, fn)
                    try:
                        size = os.path.getsize(full)
                    except OSError:
                        continue
                    out.append({"path": os.path.relpath(full, ws), "size": size})
                    if len(out) >= 3000:  # 大仓库兜底：别把整棵树都吐出来
                        break
                if len(out) >= 3000:
                    break
        out.sort(key=lambda f: f["path"])
        return {"root": ws, "name": os.path.basename(ws), "is_custom": bool(custom), "files": out}

    @app.get("/sessions/{sid}/file")
    async def read_workspace_file(sid: str, path: str, request: Request):  # 编码 IDE：读单个文件（只读、越界防护）
        ws = _session_ws(request.app, sid)
        target = os.path.realpath(os.path.join(ws, path))
        if target != ws and not target.startswith(ws + os.sep):
            raise HTTPException(400, "bad_path")
        if not os.path.isfile(target):
            raise HTTPException(404, "file_not_found")
        if os.path.getsize(target) > 400_000:
            return {"path": path, "content": "(文件过大，未加载)", "truncated": True}
        try:
            with open(target, encoding="utf-8") as f:
                content = f.read()
        except (UnicodeDecodeError, OSError):
            return {"path": path, "content": "(二进制或无法读取的文件)", "truncated": True}
        return {"path": path, "content": content, "truncated": False}

    @app.post("/sessions/{sid}/workspace")
    async def set_workspace(sid: str, body: WorkspaceIn, request: Request):  # IDE「打开文件夹」
        p = os.path.realpath(os.path.expanduser(body.path.strip()))
        if not os.path.isdir(p):
            raise HTTPException(400, "not_a_directory")
        request.app.state.workspaces[sid] = p
        _save_workspaces(request.app)
        return {"root": p, "name": os.path.basename(p), "is_custom": True}

    @app.delete("/sessions/{sid}/workspace")
    async def clear_workspace(sid: str, request: Request):  # 关掉打开的文件夹，回到默认工作区
        request.app.state.workspaces.pop(sid, None)
        _save_workspaces(request.app)
        return {"ok": True}

    @app.post("/sessions/{sid}/new-file", status_code=201)
    async def new_workspace_file(sid: str, body: NewFileIn, request: Request):  # IDE「新建文件」
        ws = _session_ws(request.app, sid)
        rel = body.path.strip().lstrip("/")
        if not rel:
            raise HTTPException(400, "empty_path")
        target = os.path.realpath(os.path.join(ws, rel))
        if target != ws and not target.startswith(ws + os.sep):
            raise HTTPException(400, "bad_path")
        if os.path.exists(target):
            raise HTTPException(409, "already_exists")
        os.makedirs(os.path.dirname(target) or ws, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(body.content or "")
        return {"path": os.path.relpath(target, ws)}

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

    # ---------- BYOK 连接 / 模型目录 / 设置（F1.2 / F1.3 / F7.2·F7.4）----------
    @app.get("/providers")
    async def list_providers(request: Request):  # 绝不返回 key
        return {"connections": request.app.state.providers.list()}

    @app.post("/providers", status_code=201)
    async def add_provider(body: ProviderIn, request: Request):
        return request.app.state.providers.add(
            body.provider, body.api_key, base_url=body.base_url, model_default=body.model_default
        )  # key 立即进 keychain，响应不含 key

    @app.post("/providers/{cid}/activate")
    async def activate_provider(cid: str, request: Request):
        if not request.app.state.providers.set_active(cid):
            raise HTTPException(404, "connection_not_found")
        return {"ok": True}

    @app.delete("/providers/{cid}")
    async def del_provider(cid: str, request: Request):
        if not request.app.state.providers.delete(cid):
            raise HTTPException(404, "connection_not_found")
        return {"ok": True}

    @app.post("/providers/{cid}/test")
    async def test_provider(cid: str, request: Request):
        import time

        ps = request.app.state.providers
        conn = ps.get(cid)
        if not conn:
            raise HTTPException(404, "connection_not_found")
        key = ps.get_key(cid)
        if conn["provider"] == "openai":
            from core.providers.openai_compat import OpenAICompatProvider

            prov: Any = OpenAICompatProvider(api_key=key, base_url=conn["base_url"])
            model = conn["model_default"] or "deepseek-chat"
        else:
            from core.providers.anthropic import AnthropicProvider

            prov = AnthropicProvider(api_key=key)
            model = conn["model_default"] or "claude-sonnet-4-6"
        t0 = time.monotonic()

        async def _probe():
            async for _ev in prov.stream(
                system="", messages=[Message(role="user", content=[TextBlock(text="hi")])],
                tools=[], model=model, max_tokens=1,
            ):
                return  # 收到首个事件即算连通

        try:
            await asyncio.wait_for(_probe(), timeout=20)
            return {"ok": True, "latency_ms": round((time.monotonic() - t0) * 1000)}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"{type(e).__name__}: {e}"[:200]}

    @app.get("/models")
    async def list_models():
        return {"models": MODELS}

    @app.get("/settings")
    async def get_settings(request: Request):
        return {"settings": request.app.state.settings.get(), "persona_suggestion": DEFAULT_PERSONA}

    @app.put("/settings")
    async def put_settings(body: SettingsIn, request: Request):
        s = request.app.state.settings.update(**body.model_dump(exclude_none=True))
        _apply_proxy(request.app)  # 代理改了即时生效
        return {"settings": s}

    @app.get("/weather")
    async def get_weather_ep(request: Request):  # 日常面板：今天/明天天气 + 建议（手动城市）
        from core.weather import get_weather

        s = request.app.state.settings.get()
        try:
            w = await get_weather(
                city=s.get("weather_city") or "", lat=s.get("weather_lat"),
                lon=s.get("weather_lon"), label=s.get("weather_label") or "",
            )
        except Exception as e:  # noqa: BLE001 - 网络/解析失败不该 500，前端按 ok=False 处理
            return {"ok": False, "reason": f"{type(e).__name__}"}
        if w.get("ok") and s.get("weather_lat") is None:  # 首次 geocode 成功 → 缓存经纬度/标签
            request.app.state.settings.update(
                weather_lat=w["lat"], weather_lon=w["lon"], weather_label=w["label"]
            )
        return w

    # ---------- 技能（导入/渐进披露，design §4.6）----------
    @app.get("/skills")
    async def list_skills(request: Request):
        return {"skills": [
            {"name": s.name, "description": s.description, "when_to_use": s.when_to_use, "files": s.files}
            for s in request.app.state.skills.list()
        ]}

    @app.get("/skills/{name}")
    async def get_skill(name: str, request: Request):
        sk = request.app.state.skills.get(name)
        if sk is None:
            raise HTTPException(404, "skill_not_found")
        return {"name": sk.name, "description": sk.description, "when_to_use": sk.when_to_use,
                "body": sk.body, "files": sk.files, "dir": sk.dir}

    @app.post("/skills/install", status_code=201)
    async def install_skill(body: SkillInstallIn, request: Request):  # 安装技能包（选含 SKILL.md 的文件夹）
        try:
            sk = request.app.state.skills.install(body.path)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, f"install_failed: {e}") from e
        return {"name": sk.name, "description": sk.description, "when_to_use": sk.when_to_use, "files": sk.files}

    @app.post("/skills", status_code=201)
    async def add_skill(body: SkillIn, request: Request):
        if not body.name.strip():
            raise HTTPException(400, "empty_name")
        sk = request.app.state.skills.add(
            body.name, description=body.description or "",
            when_to_use=body.when_to_use or "", body=body.body or "",
        )
        return {"name": sk.name, "description": sk.description, "when_to_use": sk.when_to_use}

    @app.delete("/skills/{name}")
    async def del_skill(name: str, request: Request):
        if not request.app.state.skills.delete(name):
            raise HTTPException(404, "skill_not_found")
        return {"ok": True}

    # ---------- 定时自动化 + review 队列（F6.6）----------
    @app.get("/automations")
    async def list_autos(request: Request):
        return {"automations": request.app.state.scheduler.list_automations()}

    @app.post("/automations", status_code=201)
    async def add_auto(body: AutomationIn, request: Request):
        return request.app.state.scheduler.add_automation(
            body.name, body.schedule, body.prompt, scenario=body.scenario or "assistant"
        )

    @app.patch("/automations/{aid}")
    async def patch_auto(aid: str, body: AutomationPatch, request: Request):
        a = request.app.state.scheduler.update_automation(aid, **body.model_dump(exclude_none=True))
        if a is None:
            raise HTTPException(404, "automation_not_found")
        return a

    @app.delete("/automations/{aid}")
    async def del_auto(aid: str, request: Request):
        if not request.app.state.scheduler.delete_automation(aid):
            raise HTTPException(404, "automation_not_found")
        return {"ok": True}

    @app.post("/automations/{aid}/run")
    async def run_auto(aid: str, request: Request):  # 手动触发一次（不等调度）
        a = request.app.state.scheduler.get_automation(aid)
        if not a:
            raise HTTPException(404, "automation_not_found")
        out = await _run_automation(request.app, a["prompt"], a["scenario"])
        request.app.state.scheduler.mark_automation_run(a["id"])
        return request.app.state.scheduler.add_review(a["id"], a["name"], out)

    @app.get("/review-queue")
    async def list_rq(request: Request, status: str | None = None):
        return {"reviews": request.app.state.scheduler.list_reviews(status)}

    @app.post("/review-queue/{rid}")
    async def decide_rq(rid: str, body: DecisionIn, request: Request):
        r = request.app.state.scheduler.decide_review(rid, body.decision)
        if r is None:
            raise HTTPException(404, "review_not_found")
        return r

    # 末尾挂载前端静态产物（若存在）：打包后桌面窗口直接 http://127.0.0.1:port/ 同源访问。
    # 必须在所有 API 路由之后挂载，"/" 兜底不抢 API。
    frontend = frontend_dir or os.environ.get("AGENTY_FRONTEND") or _default_frontend()
    if frontend and os.path.isdir(frontend):
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")

    return app


def _env_approval() -> ApprovalMode:
    return ApprovalMode.AUTO if os.environ.get("AGENTY_APPROVAL", "ask") == "auto" else ApprovalMode.ASK


app = create_app(approval_mode=_env_approval(), run_scheduler=True)  # 供 `uvicorn server.app:app` 使用

