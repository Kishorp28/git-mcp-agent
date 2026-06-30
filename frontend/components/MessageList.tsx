"use client";

import { MarkdownRenderer } from "./MarkdownRenderer";
import type { ChatMessage } from "@/types";

interface MessageListProps {
  messages: ChatMessage[];
  isLoading: boolean;
}

export function MessageList({ messages, isLoading }: MessageListProps) {
  if (messages.length === 0) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-4 p-8 text-center">
        <div className="rounded-2xl border border-slate-700 bg-slate-900/50 p-8 max-w-lg">
          <h2 className="mb-2 text-xl font-semibold text-slate-100">
            GitHub AI Engineer
          </h2>
          <p className="text-slate-400 text-sm leading-relaxed">
            Ask about repositories, security, architecture, or code. The agent
            uses MCP tools to read GitHub, local files, and git history.
          </p>
          <div className="mt-4 grid gap-2 text-left text-sm">
            {[
              "Explain how authentication works in this repo",
              "Find security vulnerabilities in the API layer",
              "Summarize the last 5 commits",
              "Create a GitHub issue for the login bug",
            ].map((suggestion) => (
              <div
                key={suggestion}
                className="rounded-lg border border-slate-700/50 bg-slate-800/30 px-3 py-2 text-slate-400"
              >
                &ldquo;{suggestion}&rdquo;
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-1 flex-col gap-4 overflow-y-auto p-4">
      {messages.map((msg) => (
        <div
          key={msg.id}
          className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
        >
          <div
            className={`max-w-[85%] rounded-2xl px-4 py-3 ${
              msg.role === "user"
                ? "bg-blue-600 text-white"
                : "border border-slate-700 bg-slate-900/80 text-slate-100"
            }`}
          >
            {msg.role === "assistant" ? (
              <MarkdownRenderer content={msg.content || (isLoading ? "…" : "")} />
            ) : (
              <p className="text-sm leading-relaxed">{msg.content}</p>
            )}
          </div>
        </div>
      ))}
      {isLoading && messages[messages.length - 1]?.role === "user" && (
        <div className="flex justify-start">
          <div className="rounded-2xl border border-slate-700 bg-slate-900/80 px-4 py-3">
            <div className="flex gap-1">
              <span className="h-2 w-2 animate-bounce rounded-full bg-blue-400 [animation-delay:-0.3s]" />
              <span className="h-2 w-2 animate-bounce rounded-full bg-blue-400 [animation-delay:-0.15s]" />
              <span className="h-2 w-2 animate-bounce rounded-full bg-blue-400" />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
