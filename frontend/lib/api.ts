import type { HealthStatus, MCPTool, SessionInfo, SessionHistory } from "@/types";

const API_BASE =
  typeof window !== "undefined"
    ? (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000")
    : (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000");

export { API_BASE };

// ---------------------------------------------------------------------------
// Generic fetch helpers
// ---------------------------------------------------------------------------

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `Request failed: ${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Health & Tools
// ---------------------------------------------------------------------------

export async function fetchHealth(): Promise<HealthStatus> {
  return apiFetch<HealthStatus>("/health");
}

export async function fetchTools(): Promise<MCPTool[]> {
  return apiFetch<MCPTool[]>("/tools");
}

export async function searchTools(query: string): Promise<MCPTool[]> {
  return apiFetch<MCPTool[]>(`/tools/search?q=${encodeURIComponent(query)}`);
}

export async function reconnectMCP(): Promise<{
  connected: boolean;
  tool_count: number;
  servers: string[];
}> {
  return apiFetch("/mcp/reconnect", { method: "POST" });
}

// ---------------------------------------------------------------------------
// Sessions
// ---------------------------------------------------------------------------

export async function fetchSessions(): Promise<SessionInfo[]> {
  return apiFetch<SessionInfo[]>("/sessions");
}

export async function fetchSession(sessionId: string): Promise<SessionHistory> {
  return apiFetch<SessionHistory>(`/sessions/${sessionId}`);
}

export async function deleteSession(sessionId: string): Promise<void> {
  await apiFetch(`/sessions/${sessionId}`, { method: "DELETE" });
}

export async function clearSession(sessionId: string): Promise<SessionInfo> {
  return apiFetch<SessionInfo>(`/sessions/${sessionId}/clear`, {
    method: "POST",
  });
}

// ---------------------------------------------------------------------------
// Streaming chat
// ---------------------------------------------------------------------------

export async function streamChat(
  message: string,
  onEvent: (event: string, data: Record<string, unknown>) => void,
  signal?: AbortSignal,
  sessionId?: string,
): Promise<void> {
  const body: Record<string, unknown> = { message };
  if (sessionId) body.session_id = sessionId;

  const res = await fetch(`${API_BASE}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });

  if (!res.ok) {
    const err = await res.text().catch(() => "");
    throw new Error(err || `Chat failed (${res.status})`);
  }

  const reader = res.body?.getReader();
  if (!reader) throw new Error("No response body");

  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // Process all complete SSE messages in the buffer
      // SSE messages are separated by double newlines (\n\n or \r\n\r\n)
      const messages = buffer.split(/\r?\n\r?\n/);
      // Keep the last (potentially incomplete) chunk
      buffer = messages.pop() ?? "";

      for (const msg of messages) {
        if (!msg.trim()) continue;

        const lines = msg.split("\n");
        let currentEvent = "";
        let dataLine = "";

        for (const line of lines) {
          if (line.startsWith("event:")) {
            currentEvent = line.slice(6).trim();
          } else if (line.startsWith("data:")) {
            dataLine = line.slice(5).trim();
          }
        }

        if (currentEvent && dataLine) {
          try {
            const data = JSON.parse(dataLine);
            onEvent(currentEvent, data);
          } catch {
            // skip malformed JSON
          }
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

// ---------------------------------------------------------------------------
// Synchronous chat (testing / simple clients)
// ---------------------------------------------------------------------------

export async function chatSync(
  message: string,
  sessionId?: string,
): Promise<{ response: string; session_id: string }> {
  const body: Record<string, unknown> = { message };
  if (sessionId) body.session_id = sessionId;
  return apiFetch("/chat", { method: "POST", body: JSON.stringify(body) });
}
