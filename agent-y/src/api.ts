// Agent Y 后端客户端：会话 + SSE 流 + 审批。对应 docs/design.md §4.1。
// 后端地址可用 VITE_API_BASE 覆盖，默认本机 8765。

const BASE: string =
  (import.meta as any).env?.VITE_API_BASE || "http://127.0.0.1:8765";

export type Frame =
  | { type: "text_delta"; text: string }
  | { type: "thinking_delta"; text: string }
  | { type: "tool_use"; id: string; name: string; input: Record<string, any> }
  | { type: "tool_result"; id: string; is_error: boolean; preview: string }
  | { type: "approval_request"; approval_id: string; tool: string; summary?: string; risk: string }
  | { type: "usage"; input_tokens: number; output_tokens: number }
  | { type: "span"; span: any }
  | { type: "done"; reason: string }
  | { type: "error"; message: string; code?: string };

export interface SessionSummary {
  id: string;
  title: string;
  scenario: string;
  status: string;
  updated_at: string;
  message_count: number;
}

export async function createSession(title?: string, scenario = "coding"): Promise<string> {
  const r = await fetch(`${BASE}/sessions`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ title, scenario }),
  });
  if (!r.ok) throw new Error(`createSession failed: ${r.status}`);
  return (await r.json()).session_id;
}

export async function listSessions(): Promise<SessionSummary[]> {
  const r = await fetch(`${BASE}/sessions`);
  if (!r.ok) return [];
  return (await r.json()).sessions ?? [];
}

export async function getSessionMessages(sid: string): Promise<{ role: string; content: any[] }[]> {
  const r = await fetch(`${BASE}/sessions/${sid}`);
  if (!r.ok) return [];
  return (await r.json()).messages ?? [];
}

export async function postApproval(approvalId: string, decision: "allow" | "deny"): Promise<void> {
  await fetch(`${BASE}/approvals/${approvalId}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ decision }),
  });
}

export async function interruptSession(sid: string): Promise<void> {
  await fetch(`${BASE}/sessions/${sid}/interrupt`, { method: "POST" });
}

// 发消息并逐帧消费 SSE（text/event-stream）。用法：for await (const fr of streamMessage(sid, text)) {...}
export async function* streamMessage(sid: string, text: string): AsyncGenerator<Frame> {
  const r = await fetch(`${BASE}/sessions/${sid}/messages`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ text }),
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
        try {
          yield JSON.parse(line.slice(6)) as Frame;
        } catch {
          /* 跳过不完整帧 */
        }
      }
    }
  }
}
