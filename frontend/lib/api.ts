const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function fetchHealth() {
  const res = await fetch(`${API_BASE}/health`);
  if (!res.ok) throw new Error("Health check failed");
  return res.json();
}

export async function fetchTools() {
  const res = await fetch(`${API_BASE}/tools`);
  if (!res.ok) throw new Error("Failed to fetch tools");
  return res.json();
}

export async function streamChat(
  message: string,
  onEvent: (event: string, data: Record<string, unknown>) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${API_BASE}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
    signal,
  });

  if (!res.ok) {
    const err = await res.text();
    throw new Error(err || `Chat failed (${res.status})`);
  }

  const reader = res.body?.getReader();
  if (!reader) throw new Error("No response body");

  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    let currentEvent = "";
    for (const line of lines) {
      if (line.startsWith("event:")) {
        currentEvent = line.slice(6).trim();
      } else if (line.startsWith("data:") && currentEvent) {
        try {
          const data = JSON.parse(line.slice(5).trim());
          onEvent(currentEvent, data);
        } catch {
          // skip malformed JSON
        }
        currentEvent = "";
      }
    }
  }
}

export { API_BASE };
