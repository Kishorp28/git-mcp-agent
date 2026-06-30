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
}

export interface HealthStatus {
  status: string;
  mcp_connected: boolean;
  tool_count: number;
  llm_configured: boolean;
  servers: string[];
}

export interface MCPTool {
  name: string;
  description: string;
  server: string | null;
  input_schema: Record<string, unknown>;
}

export type StreamEventType =
  | "status"
  | "message_start"
  | "message_delta"
  | "message_end"
  | "tool_start"
  | "tool_end"
  | "tool_error"
  | "error";

export interface StreamEvent {
  type: StreamEventType;
  content?: string;
  message?: string;
  name?: string;
  arguments?: Record<string, unknown>;
  result?: string;
  error?: string;
}
