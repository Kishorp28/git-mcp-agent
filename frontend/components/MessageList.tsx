"use client";

import { useEffect, useRef, useState } from "react";
import { MarkdownRenderer } from "./MarkdownRenderer";
import type { ChatMessage } from "@/types";

interface MessageListProps {
  messages: ChatMessage[];
  isLoading: boolean;
}

function formatTime(date: Date): string {
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // clipboard not available
    }
  };

  return (
    <button
      onClick={handleCopy}
      className="rounded p-1 text-slate-500 opacity-0 transition-opacity group-hover:opacity-100 hover:bg-slate-700/60 hover:text-slate-300"
      title="Copy message"
      aria-label="Copy message"
    >
      {copied ? (
        <svg className="h-3.5 w-3.5 text-green-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
        </svg>
      ) : (
        <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
        </svg>
      )}
    </button>
  );
}

const SUGGESTIONS = [
  "Explain how authentication works in this repo",
  "Find security vulnerabilities in the API layer",
  "Summarize the last 5 commits",
  "Create a GitHub issue for the login bug",
];

export function MessageList({ messages, isLoading }: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [isAtBottom, setIsAtBottom] = useState(true);
  const [showScrollBtn, setShowScrollBtn] = useState(false);

  // Auto-scroll to bottom when new content arrives (only if already near bottom)
  useEffect(() => {
    if (isAtBottom) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, isAtBottom]);

  // Show "scroll to bottom" button when user has scrolled up
  const handleScroll = () => {
    const el = containerRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 100;
    setIsAtBottom(nearBottom);
    setShowScrollBtn(!nearBottom);
  };

  const scrollToBottom = () => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    setIsAtBottom(true);
    setShowScrollBtn(false);
  };

  if (messages.length === 0) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-4 p-8 text-center">
        <div className="w-full max-w-lg rounded-2xl border border-slate-700/60 bg-slate-900/50 p-8">
          <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-blue-600/20 mx-auto">
            <svg className="h-6 w-6 text-blue-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M17.25 6.75L22.5 12l-5.25 5.25m-10.5 0L1.5 12l5.25-5.25m7.5-3l-4.5 16.5" />
            </svg>
          </div>
          <h2 className="mb-1 text-xl font-semibold text-slate-100">
            GitHub AI Engineer
          </h2>
          <p className="mb-5 text-sm leading-relaxed text-slate-400">
            Ask about repositories, security, architecture, or code. The agent
            uses MCP tools to read GitHub, local files, and git history.
          </p>
          <div className="grid gap-2 text-left">
            {SUGGESTIONS.map((s) => (
              <div
                key={s}
                className="rounded-lg border border-slate-700/40 bg-slate-800/30 px-3 py-2 text-sm text-slate-400"
              >
                &ldquo;{s}&rdquo;
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="relative flex flex-1 flex-col overflow-hidden">
      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="flex flex-1 flex-col gap-4 overflow-y-auto p-4 pb-2"
      >
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`group flex items-start gap-2 ${
              msg.role === "user" ? "flex-row-reverse" : "flex-row"
            }`}
          >
            {/* Avatar */}
            <div
              className={`mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-bold ${
                msg.role === "user"
                  ? "bg-blue-600 text-white"
                  : "bg-slate-700 text-slate-300"
              }`}
            >
              {msg.role === "user" ? "U" : "AI"}
            </div>

            {/* Bubble */}
            <div className="flex max-w-[82%] flex-col gap-1">
              <div
                className={`rounded-2xl px-4 py-3 text-sm ${
                  msg.role === "user"
                    ? "rounded-tr-sm bg-blue-600 text-white"
                    : "rounded-tl-sm border border-slate-700/60 bg-slate-900/80 text-slate-100"
                }`}
              >
                {msg.role === "assistant" ? (
                  <MarkdownRenderer
                    content={msg.content || (isLoading ? "" : "")}
                  />
                ) : (
                  <p className="leading-relaxed">{msg.content}</p>
                )}
              </div>

              {/* Timestamp + copy */}
              <div
                className={`flex items-center gap-1 px-1 ${
                  msg.role === "user" ? "flex-row-reverse" : "flex-row"
                }`}
              >
                <span className="text-xs text-slate-600">
                  {formatTime(msg.timestamp)}
                </span>
                <CopyButton text={msg.content} />
              </div>
            </div>
          </div>
        ))}

        {/* Typing indicator */}
        {isLoading && messages[messages.length - 1]?.role === "user" && (
          <div className="flex items-start gap-2">
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-slate-700 text-xs font-bold text-slate-300">
              AI
            </div>
            <div className="rounded-2xl rounded-tl-sm border border-slate-700/60 bg-slate-900/80 px-4 py-3">
              <div className="flex gap-1.5">
                <span className="h-2 w-2 animate-bounce rounded-full bg-blue-400 [animation-delay:-0.3s]" />
                <span className="h-2 w-2 animate-bounce rounded-full bg-blue-400 [animation-delay:-0.15s]" />
                <span className="h-2 w-2 animate-bounce rounded-full bg-blue-400" />
              </div>
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Scroll-to-bottom button */}
      {showScrollBtn && (
        <button
          onClick={scrollToBottom}
          className="absolute bottom-4 right-4 flex h-8 w-8 items-center justify-center rounded-full border border-slate-600 bg-slate-800 text-slate-300 shadow-lg transition hover:bg-slate-700"
          aria-label="Scroll to bottom"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
          </svg>
        </button>
      )}
    </div>
  );
}
