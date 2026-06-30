"use client";

import { useCallback, useRef, useState } from "react";
import { streamChat } from "@/lib/api";
import type { ChatMessage, ToolLogEntry } from "@/types";

function uid() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [toolLogs, setToolLogs] = useState<ToolLogEntry[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const sendMessage = useCallback(async (content: string) => {
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
    let assistantContent = "";

    abortRef.current = new AbortController();

    try {
      await streamChat(
        content.trim(),
        (event, data) => {
          switch (event) {
            case "status":
              setStatus(data.message as string);
              break;
            case "message_start":
              setMessages((prev) => [
                ...prev,
                {
                  id: assistantId,
                  role: "assistant",
                  content: "",
                  timestamp: new Date(),
                },
              ]);
              break;
            case "message_delta":
              assistantContent += (data.content as string) ?? "";
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantId ? { ...m, content: assistantContent } : m,
                ),
              );
              break;
            case "tool_start":
              setToolLogs((prev) => [
                ...prev,
                {
                  id: uid(),
                  name: data.name as string,
                  arguments: (data.arguments as Record<string, unknown>) ?? {},
                  status: "running",
                  timestamp: new Date(),
                },
              ]);
              break;
            case "tool_end":
              setToolLogs((prev) => {
                const copy = [...prev];
                for (let i = copy.length - 1; i >= 0; i--) {
                  if (copy[i].name === data.name && copy[i].status === "running") {
                    copy[i] = {
                      ...copy[i],
                      status: "success",
                      result: data.result as string,
                    };
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
                  if (copy[i].name === data.name && copy[i].status === "running") {
                    copy[i] = {
                      ...copy[i],
                      status: "error",
                      error: data.error as string,
                    };
                    break;
                  }
                }
                return copy;
              });
              break;
            case "error":
              setStatus(`Error: ${data.message}`);
              break;
          }
        },
        abortRef.current.signal,
      );
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        setMessages((prev) => [
          ...prev,
          {
            id: uid(),
            role: "assistant",
            content: `**Error:** ${(err as Error).message}`,
            timestamp: new Date(),
          },
        ]);
      }
    } finally {
      setIsLoading(false);
      setStatus(null);
      abortRef.current = null;
    }
  }, [isLoading]);

  const clearChat = useCallback(() => {
    abortRef.current?.abort();
    setMessages([]);
    setToolLogs([]);
    setStatus(null);
    setIsLoading(false);
  }, []);

  return { messages, toolLogs, isLoading, status, sendMessage, clearChat };
}
