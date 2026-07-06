"use client";

import { useCallback, useRef, useState } from "react";
import { streamChat } from "@/lib/api";
import type { ChatMessage, ToolLogEntry } from "@/types";

function uid(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

export interface UseChatReturn {
  messages: ChatMessage[];
  toolLogs: ToolLogEntry[];
  isLoading: boolean;
  status: string | null;
  sessionId: string | null;
  sendMessage: (content: string) => Promise<void>;
  clearChat: () => void;
  stopGeneration: () => void;
}

export function useChat(initialSessionId?: string): UseChatReturn {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [toolLogs, setToolLogs] = useState<ToolLogEntry[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(
    initialSessionId ?? null,
  );

  const abortRef = useRef<AbortController | null>(null);
  // Track tool start timestamps for duration calculation
  const toolStartTimes = useRef<Map<string, number>>(new Map());

  const stopGeneration = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const sendMessage = useCallback(
    async (content: string) => {
      if (!content.trim() || isLoading) return;

      const userMsg: ChatMessage = {
        id: uid(),
        role: "user",
        content: content.trim(),
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, userMsg]);
      setIsLoading(true);
      setStatus("Connecting to agent…");

      const assistantId = uid();
      const assistantContentRef = { current: "" };

      abortRef.current = new AbortController();

      try {
        await streamChat(
          content.trim(),
          (event, data) => {
            switch (event) {
              case "session":
                if (data.session_id) {
                  setSessionId(data.session_id as string);
                }
                break;

              case "status":
                setStatus(data.message as string);
                break;

              case "message_start":
                assistantContentRef.current = "";
                setMessages((prev) => {
                  if (prev.some((m) => m.id === assistantId)) return prev;
                  return [
                    ...prev,
                    {
                      id: assistantId,
                      role: "assistant",
                      content: "",
                      timestamp: new Date(),
                    },
                  ];
                });
                break;

              case "message_delta": {
                const chunk = (data.content as string) ?? "";
                assistantContentRef.current += chunk;
                setMessages((prev) => {
                  const exists = prev.some((m) => m.id === assistantId);
                  if (exists) {
                    return prev.map((m) =>
                      m.id === assistantId
                        ? { ...m, content: assistantContentRef.current }
                        : m,
                    );
                  } else {
                    return [
                      ...prev,
                      {
                        id: assistantId,
                        role: "assistant",
                        content: assistantContentRef.current,
                        timestamp: new Date(),
                      },
                    ];
                  }
                });
                break;
              }

              case "message_end":
                // Message is complete; status is cleared in finally
                break;

              case "tool_start": {
                const toolId = uid();
                toolStartTimes.current.set(data.name as string, Date.now());
                setToolLogs((prev) => [
                  ...prev,
                  {
                    id: toolId,
                    name: data.name as string,
                    arguments:
                      (data.arguments as Record<string, unknown>) ?? {},
                    status: "running",
                    timestamp: new Date(),
                  },
                ]);
                break;
              }

              case "tool_end":
                setToolLogs((prev) => {
                  const copy = [...prev];
                  for (let i = copy.length - 1; i >= 0; i--) {
                    if (
                      copy[i].name === data.name &&
                      copy[i].status === "running"
                    ) {
                      const started =
                        toolStartTimes.current.get(data.name as string) ??
                        Date.now();
                      copy[i] = {
                        ...copy[i],
                        status: "success",
                        result: data.result as string,
                        durationMs: Date.now() - started,
                      };
                      toolStartTimes.current.delete(data.name as string);
                      break;
                    }
                  }
                  return copy;
                });
                break;

              case "tool_error":
                setToolLogs((prev) => {
                  const copy = [...prev];
                  for (let i = copy.length - 1; i >= 0; i--) {
                    if (
                      copy[i].name === data.name &&
                      copy[i].status === "running"
                    ) {
                      copy[i] = {
                        ...copy[i],
                        status: "error",
                        error: data.error as string,
                        durationMs:
                          Date.now() -
                          (toolStartTimes.current.get(
                            data.name as string,
                          ) ?? Date.now()),
                      };
                      toolStartTimes.current.delete(data.name as string);
                      break;
                    }
                  }
                  return copy;
                });
                break;

              case "error": {
                const errMsg = data.message as string;
                // Always show the error as a visible assistant message
                setMessages((prev) => {
                  const hasAssistant = prev.some((m) => m.id === assistantId);
                  if (hasAssistant) {
                    // Update the existing bubble only if it's still empty
                    return prev.map((m) =>
                      m.id === assistantId && !m.content
                        ? { ...m, content: `**Error:** ${errMsg}` }
                        : m,
                    );
                  }
                  // No bubble yet — create one
                  return [
                    ...prev,
                    {
                      id: assistantId,
                      role: "assistant" as const,
                      content: `**Error:** ${errMsg}`,
                      timestamp: new Date(),
                    },
                  ];
                });
                setStatus(null);
                break;
              }
            }
          },
          abortRef.current.signal,
          sessionId ?? undefined,
        );
      } catch (err) {
        const error = err as Error;
        if (error.name === "AbortError") {
          // User cancelled — mark partial response as complete
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId && !m.content
                ? { ...m, content: "_Generation stopped._" }
                : m,
            ),
          );
        } else {
          setMessages((prev) => {
            const hasAssistant = prev.some((m) => m.id === assistantId);
            if (hasAssistant) return prev;
            return [
              ...prev,
              {
                id: uid(),
                role: "assistant",
                content: `**Connection error:** ${error.message}`,
                timestamp: new Date(),
              },
            ];
          });
        }
      } finally {
        setIsLoading(false);
        setStatus(null);
        abortRef.current = null;
        toolStartTimes.current.clear();
      }
    },
    [isLoading, sessionId],
  );

  const clearChat = useCallback(() => {
    abortRef.current?.abort();
    setMessages([]);
    setToolLogs([]);
    setStatus(null);
    setIsLoading(false);
    setSessionId(null);
    toolStartTimes.current.clear();
  }, []);

  return {
    messages,
    toolLogs,
    isLoading,
    status,
    sessionId,
    sendMessage,
    clearChat,
    stopGeneration,
  };
}
