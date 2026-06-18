// Agent Y 后端客户端：会话 + SSE 流 + 审批 + BYOK/设置/助手。对应 docs/design.md §4.1。
// 默认同源（打包后桌面窗口与后端同在 127.0.0.1:8765）；dev 用 VITE_API_BASE 指向后端。

const BASE: string = (import.meta as any).env?.VITE_API_BASE ?? "";

export type Frame =
  | { type: "text_delta"; text: string }
  | { type: "thinking_delta"; text: string }
  | { type: "tool_use"; id: string; name: string; input: Record<string, any> }
  | { type: "tool_result"; id: string; is_error: boolean; preview: string }
  | { type: "approval_request"; approval_id: string; tool: string; summary?: string; risk: string }
  | { type: "usage"; input_tokens: number; output_tokens: number }
  | { type: "file_change"; path: string; diff: string; old: string }
  | { type: "done"; reason: string }
  | { type: "error"; message: string; code?: string };

export interface SessionSummary {
  id: string; title: string; scenario: string; status: string;
  updated_at: string; message_count: number;
}
export interface Connection {
  id: string; provider: string; base_url?: string | null;
  model_default?: string | null; active: boolean; created_at: string;
}
export interface ModelInfo {
  id: string; provider: string; label: string; context_window: number;
  supports_tools: boolean; supports_thinking: boolean; price_in: number; price_out: number;
}
export interface Settings {
  agent_name: string; persona: string; default_model: string;
  models?: Record<string, string>;  // 按角色配模型 {orchestrator|subagent|judge}（F1.4）
  approval_mode: string | null; sandbox?: string;
  weather_city?: string; weather_label?: string;  // 日常面板天气城市（手动）
  proxy?: string;  // 网络代理：auto / 空 / http://host:port
}
export interface Todo { id: string; text: string; done: boolean; due?: string | null; created_at: string; }
export interface Folder { id: string; path: string; mode: string; }
export interface WeatherDay {
  date: string; code: number; text: string;
  tmax: number | null; tmin: number | null; precip_prob: number | null;
}
export interface WeatherCurrent {
  temp: number | null; feels: number | null; humidity: number | null; wind: number | null; code: number; text: string;
}
export interface WeatherHour { time: string; temp: number | null; code: number; text: string; }
export interface Weather {
  ok: boolean; reason?: string; label?: string;
  today?: WeatherDay | null; tomorrow?: WeatherDay | null;
  current?: WeatherCurrent | null; hourly?: WeatherHour[]; advice?: string;
}
export interface SkillMeta { name: string; description: string; when_to_use: string; files?: string[]; }

async function j<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${BASE}${url}`, init);
  if (!r.ok) throw new Error(`${init?.method || "GET"} ${url} → ${r.status}`);
  return (await r.json()) as T;
}
const post = (url: string, body?: any) =>
  j(url, { method: "POST", headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });

// ---------- 会话 ----------
export async function createSession(title?: string, scenario = "coding"): Promise<string> {
  return (await post("/sessions", { title, scenario }) as any).session_id;
}
export async function listSessions(): Promise<SessionSummary[]> {
  return j<{ sessions: SessionSummary[] }>("/sessions").then((d) => d.sessions ?? []).catch(() => []);
}
export async function getSessionMessages(sid: string): Promise<{ role: string; content: any[] }[]> {
  return j<{ messages: any[] }>(`/sessions/${sid}`).then((d) => d.messages ?? []).catch(() => []);
}
export const postApproval = (approvalId: string, decision: "allow" | "deny") =>
  post(`/approvals/${approvalId}`, { decision });
export const interruptSession = (sid: string) => post(`/sessions/${sid}/interrupt`);
export const deleteSession = (sid: string) => j(`/sessions/${sid}`, { method: "DELETE" });
export const renameSession = (sid: string, title: string) =>
  j(`/sessions/${sid}`, { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ title }) });
export const revertFile = (sid: string, path: string, content: string) => post(`/sessions/${sid}/revert`, { path, content });

// 编码 IDE：工作区文件树 / 读单文件 / 打开文件夹 / 新建文件
export interface WorkspaceFile { path: string; size: number; }
export interface WorkspaceInfo { root: string; name: string; is_custom: boolean; files: WorkspaceFile[]; }
export const listWorkspaceFiles = (sid: string) =>
  j<WorkspaceInfo>(`/sessions/${sid}/files`).catch(() => ({ root: '', name: '', is_custom: false, files: [] as WorkspaceFile[] }));
export const readWorkspaceFile = (sid: string, path: string) =>
  j<{ path: string; content: string; truncated: boolean }>(`/sessions/${sid}/file?path=${encodeURIComponent(path)}`)
    .catch(() => ({ path, content: '(读取失败)', truncated: false }));
export const setWorkspace = (sid: string, path: string) =>
  post(`/sessions/${sid}/workspace`, { path }) as Promise<{ root: string; name: string; is_custom: boolean }>;
export const clearWorkspace = (sid: string) => j(`/sessions/${sid}/workspace`, { method: 'DELETE' });
export const newWorkspaceFile = (sid: string, path: string, content?: string) =>
  post(`/sessions/${sid}/new-file`, { path, content }) as Promise<{ path: string }>;

// ---------- BYOK / 模型 / 设置 ----------
export const listProviders = () => j<{ connections: Connection[] }>("/providers").then((d) => d.connections ?? []).catch(() => []);
export const addProvider = (p: { provider: string; api_key: string; base_url?: string; model_default?: string }) => post("/providers", p);
export const activateProvider = (id: string) => post(`/providers/${id}/activate`);
export const deleteProvider = (id: string) => j(`/providers/${id}`, { method: "DELETE" });
export const testProvider = (id: string) => post(`/providers/${id}/test`) as Promise<{ ok: boolean; latency_ms?: number; error?: string }>;
export const listModels = () => j<{ models: ModelInfo[] }>("/models").then((d) => d.models ?? []).catch(() => []);
export const getSettings = () => j<{ settings: Settings; persona_suggestion: string }>("/settings");
export const putSettings = (s: Partial<Settings>) => j<{ settings: Settings }>("/settings", {
  method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(s),
});

// ---------- 助手：待办 / 授权目录 ----------
export const listTodos = () => j<{ todos: Todo[] }>("/todos").then((d) => d.todos ?? []).catch(() => []);
export const addTodo = (text: string, due?: string) => post("/todos", { text, due });
export const patchTodo = (id: string, patch: Partial<Todo>) => j(`/todos/${id}`, { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify(patch) });
export const deleteTodo = (id: string) => j(`/todos/${id}`, { method: "DELETE" });
export const listFolders = () => j<{ folders: Folder[] }>("/folders").then((d) => d.folders ?? []).catch(() => []);
export const addFolder = (path: string, mode = "read_write") => post("/folders", { path, mode });
export const deleteFolder = (id: string) => j(`/folders/${id}`, { method: "DELETE" });
export const getWeather = () => j<Weather>("/weather").catch(() => ({ ok: false } as Weather));

// ---------- 技能（导入/渐进披露）----------
export const listSkills = () => j<{ skills: SkillMeta[] }>("/skills").then((d) => d.skills ?? []).catch(() => []);
export const getSkill = (name: string) =>
  j<{ name: string; description: string; when_to_use: string; body: string }>(`/skills/${encodeURIComponent(name)}`);
export const addSkill = (s: { name: string; description?: string; when_to_use?: string; body?: string }) => post("/skills", s);
export const installSkill = (path: string) =>
  post("/skills/install", { path }) as Promise<{ name: string; description: string; when_to_use: string; files: string[] }>;
export const deleteSkill = (name: string) => j(`/skills/${encodeURIComponent(name)}`, { method: "DELETE" });

// 原生目录选择：打包的 pywebview 窗口注入了 window.pywebview.api.pick_folder；浏览器 dev 时没有
export const hasNativeFolderPick = (): boolean =>
  typeof (window as any).pywebview?.api?.pick_folder === "function";
export async function pickFolderNative(): Promise<string | null> {
  try { return (await (window as any).pywebview.api.pick_folder()) || null; }
  catch { return null; }
}

// ---------- 定时自动化 + 待审队列 ----------
export interface Automation {
  id: string; name: string; schedule: string; prompt: string; scenario: string;
  enabled: boolean; last_run?: string | null; created_at: string;
}
export interface Review {
  id: string; automation_id: string; title: string; output: string; status: string; created_at: string;
}
export const listAutomations = () => j<{ automations: Automation[] }>("/automations").then((d) => d.automations ?? []).catch(() => []);
export const addAutomation = (a: { name: string; schedule: string; prompt: string; scenario?: string }) => post("/automations", a);
export const patchAutomation = (id: string, patch: Partial<Automation>) =>
  j(`/automations/${id}`, { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify(patch) });
export const deleteAutomation = (id: string) => j(`/automations/${id}`, { method: "DELETE" });
export const runAutomation = (id: string) => post(`/automations/${id}/run`) as Promise<Review>;
export const listReviews = (status?: string) =>
  j<{ reviews: Review[] }>(`/review-queue${status ? `?status=${status}` : ""}`).then((d) => d.reviews ?? []).catch(() => []);
export const decideReview = (id: string, decision: "accept" | "discard") => post(`/review-queue/${id}`, { decision });

// 发消息并逐帧消费 SSE（text/event-stream）。
export async function* streamMessage(sid: string, text: string): AsyncGenerator<Frame> {
  const r = await fetch(`${BASE}/sessions/${sid}/messages`, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ text }),
  });
  if (!r.ok || !r.body) {
    yield { type: "error", message: `请求失败: ${r.status}` };
    yield { type: "done", reason: "error" };
    return;
  }
  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      const line = chunk.split("\n").find((l) => l.startsWith("data: "));
      if (line) {
        try { yield JSON.parse(line.slice(6)) as Frame; } catch { /* 跳过不完整帧 */ }
      }
    }
  }
}
