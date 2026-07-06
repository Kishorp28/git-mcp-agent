export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
}

export interface ToolLogEntry {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
  result?: string;
  error?: string;
  status: "running" | "success" | "error";
  timestamp: Date;
  durationMs?: number;
}

export interface HealthStatus {
  status: string;
  mcp_connected: boolean;
  tool_count: number;
  llm_configured: boolean;
  llm_provider: string | null;
  llm_model: string | null;
  servers: string[];
  active_sessions: number;
}

export interface MCPTool {
  name: string;
  description: string;
  server: string | null;
  input_schema: Record<string, unknown>;
}

export interface SessionInfo {
  id: string;
  message_count: number;
  created_at: number;
  last_active: number;
}

export interface SessionHistory extends SessionInfo {
  history: Array<{ role: string; content: string }>;
}

export type StreamEventType =
  | "status"
  | "message_start"
  | "message_delta"
  | "message_end"
  | "tool_start"
  | "tool_end"
  | "tool_error"
  | "error"
  | "session";

export interface StreamEvent {
  type: StreamEventType;
  content?: string;
  message?: string;
  name?: string;
  arguments?: Record<string, unknown>;
  result?: string;
  error?: string;
  session_id?: string;
}
