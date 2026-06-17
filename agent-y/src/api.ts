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
  agent_name: string; persona: string; default_model: string; approval_mode: string | null;
}
export interface Todo { id: string; text: string; done: boolean; due?: string | null; created_at: string; }
export interface Folder { id: string; path: string; mode: string; }

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
