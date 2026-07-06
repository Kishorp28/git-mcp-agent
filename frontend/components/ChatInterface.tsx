"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { MessageList } from "./MessageList";
import { StatusBar } from "./StatusBar";
import { ToolLogPanel } from "./ToolLogPanel";
import { SessionSidebar } from "./SessionSidebar";
import { useChat } from "@/hooks/useChat";

export function ChatInterface() {
  const {
    messages,
    toolLogs,
    isLoading,
    status,
    sessionId,
    sendMessage,
    clearChat,
    stopGeneration,
  } = useChat();

  const [input, setInput] = useState("");
  const [showSidebar, setShowSidebar] = useState(false);
  const [showTools, setShowTools] = useState(true);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Auto-focus input on mount
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      // Ctrl/Cmd + K → focus input
      if ((e.ctrlKey || e.metaKey) && e.key === "k") {
        e.preventDefault();
        inputRef.current?.focus();
      }
      // Ctrl/Cmd + L → clear chat
      if ((e.ctrlKey || e.metaKey) && e.key === "l") {
        e.preventDefault();
        handleClear();
      }
      // Ctrl/Cmd + B → toggle sidebar
      if ((e.ctrlKey || e.metaKey) && e.key === "b") {
        e.preventDefault();
        setShowSidebar((v) => !v);
      }
      // Escape → stop generation (if loading) or blur input
      if (e.key === "Escape") {
        if (isLoading) {
          stopGeneration();
        } else {
          inputRef.current?.blur();
        }
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [isLoading, stopGeneration]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    const trimmed = input.trim();
    if (!trimmed) return;
    sendMessage(trimmed);
    setInput("");
    // Reset textarea height
    if (inputRef.current) {
      inputRef.current.style.height = "auto";
    }
  };

  const handleClear = useCallback(() => {
    clearChat();
    setInput("");
    setTimeout(() => inputRef.current?.focus(), 50);
  }, [clearChat]);

  // Auto-resize textarea
  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    e.target.style.height = "auto";
    e.target.style.height = `${Math.min(e.target.scrollHeight, 160)}px`;
  };

  // Submit on Enter (Shift+Enter for newline)
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e as unknown as FormEvent);
    }
  };

  const handleSessionSelect = (id: string) => {
    // For now, selecting a session shows its ID in a new chat
    // A full implementation would load the history from the API
    clearChat();
    setShowSidebar(false);
  };

  return (
    <div className="flex h-screen flex-col bg-[var(--background)] text-[var(--foreground)]">
      {/* Top header */}
      <header className="flex shrink-0 items-center justify-between border-b border-slate-700/60 px-4 py-3">
        <div className="flex items-center gap-3">
          {/* Sidebar toggle */}
          <button
            onClick={() => setShowSidebar((v) => !v)}
            className={`rounded-lg p-1.5 transition-colors ${
              showSidebar
                ? "bg-slate-700 text-slate-200"
                : "text-slate-500 hover:bg-slate-800 hover:text-slate-300"
            }`}
            title="Toggle session history (Ctrl+B)"
            aria-label="Toggle session history"
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25H12" />
            </svg>
          </button>

          <div>
            <h1 className="text-sm font-bold tracking-tight text-slate-100">
              GitHub AI Engineer
            </h1>
            <p className="text-xs text-slate-500">
              MCP Host · Multi-server agent
              {sessionId && (
                <span className="ml-2 font-mono text-slate-600">
                  {sessionId.slice(0, 8)}
                </span>
              )}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* Tool panel toggle (desktop) */}
          <button
            onClick={() => setShowTools((v) => !v)}
            className="hidden items-center gap-1.5 rounded-lg border border-slate-700 px-2.5 py-1.5 text-xs text-slate-400 transition hover:border-slate-500 hover:text-slate-200 lg:flex"
            title="Toggle tool logs"
          >
            <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M11.42 15.17L17.25 21A2.652 2.652 0 0021 17.25l-5.877-5.877M11.42 15.17l2.496-3.03c.317-.384.74-.626 1.208-.766M11.42 15.17l-4.655 5.653a2.548 2.548 0 11-3.586-3.586l6.837-5.63m5.108-.233c.55-.164 1.163-.188 1.743-.14a4.5 4.5 0 004.486-6.336l-3.276 3.277a3.004 3.004 0 01-2.25-2.25l3.276-3.276a4.5 4.5 0 00-6.336 4.486c.091 1.076-.071 2.264-.904 2.95l-.102.085m-1.745 1.437L5.909 7.5H4.5L2.25 3.75l1.5-1.5L7.5 4.5v1.409l4.26 4.26m-1.745 1.437l1.745-1.437m6.615 8.206L15.75 15.75M4.867 19.125h.008v.008h-.008v-.008z" />
            </svg>
            Tools {toolLogs.length > 0 && `(${toolLogs.length})`}
          </button>

          <button
            onClick={handleClear}
            className="rounded-lg border border-slate-700 px-2.5 py-1.5 text-xs text-slate-400 transition hover:border-slate-500 hover:text-slate-200"
            title="Clear chat (Ctrl+L)"
          >
            Clear
          </button>
        </div>
      </header>

      {/* MCP status bar */}
      <StatusBar />

      {/* Body */}
      <div className="flex flex-1 overflow-hidden">
        {/* Session sidebar */}
        {showSidebar && (
          <SessionSidebar
            currentSessionId={sessionId}
            onSelectSession={handleSessionSelect}
            onNewChat={handleClear}
          />
        )}

        {/* Main chat area */}
        <main className="flex flex-1 flex-col overflow-hidden">
          <MessageList messages={messages} isLoading={isLoading} />

          {/* Agent status line */}
          {status && (
            <div className="flex items-center gap-2 border-t border-slate-800 px-4 py-2 text-xs text-slate-500">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-blue-400" />
              {status}
            </div>
          )}

          {/* Input area */}
          <form
            onSubmit={handleSubmit}
            className="shrink-0 border-t border-slate-700/60 p-4"
          >
            <div className="flex items-end gap-2">
              <textarea
                ref={inputRef}
                value={input}
                onChange={handleInputChange}
                onKeyDown={handleKeyDown}
                placeholder="Ask about code, security, architecture, GitHub…  (Enter to send, Shift+Enter for newline)"
                disabled={isLoading}
                rows={1}
                className="max-h-40 flex-1 resize-none rounded-xl border border-slate-700 bg-slate-900/60 px-4 py-3 text-sm text-slate-100 placeholder-slate-500 outline-none transition focus:border-blue-500/60 disabled:opacity-50"
                style={{ height: "auto" }}
              />
              {isLoading ? (
                <button
                  type="button"
                  onClick={stopGeneration}
                  className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-slate-600 bg-slate-800 text-slate-300 transition hover:bg-slate-700"
                  title="Stop generation (Escape)"
                >
                  <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 24 24">
                    <rect x="6" y="6" width="12" height="12" rx="1" />
                  </svg>
                </button>
              ) : (
                <button
                  type="submit"
                  disabled={!input.trim()}
                  className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-blue-600 text-white transition hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-40"
                  title="Send (Enter)"
                >
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6 12L3.269 3.126A59.768 59.768 0 0121.485 12 59.77 59.77 0 013.27 20.876L5.999 12zm0 0h7.5" />
                  </svg>
                </button>
              )}
            </div>

            <p className="mt-2 text-center text-xs text-slate-700">
              Ctrl+K focus · Ctrl+L clear · Ctrl+B sidebar · Esc stop
            </p>
          </form>
        </main>

        {/* Tool logs panel (desktop) */}
        {showTools && (
          <aside className="hidden w-80 flex-col border-l border-slate-700/60 lg:flex">
            <div className="flex items-center justify-between border-b border-slate-700/60 px-4 py-3">
              <div>
                <h2 className="text-sm font-semibold text-slate-300">Tool Logs</h2>
                <p className="text-xs text-slate-500">MCP tool invocations</p>
              </div>
              {toolLogs.length > 0 && (
                <span className="rounded-full bg-blue-600/20 px-2 py-0.5 text-xs text-blue-400">
                  {toolLogs.length}
                </span>
              )}
            </div>
            <div className="flex-1 overflow-hidden">
              <ToolLogPanel
                logs={toolLogs}
                onClear={toolLogs.length > 0 ? handleClear : undefined}
              />
            </div>
          </aside>
        )}
      </div>
    </div>
  );
}
