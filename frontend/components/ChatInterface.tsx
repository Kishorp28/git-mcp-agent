"use client";

import { FormEvent, useState } from "react";
import { MessageList } from "./MessageList";
import { StatusBar } from "./StatusBar";
import { ToolLogPanel } from "./ToolLogPanel";
import { useChat } from "@/hooks/useChat";

export function ChatInterface() {
  const { messages, toolLogs, isLoading, status, sendMessage, clearChat } =
    useChat();
  const [input, setInput] = useState("");

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!input.trim()) return;
    sendMessage(input);
    setInput("");
  };

  return (
    <div className="flex h-screen flex-col">
      <header className="flex items-center justify-between border-b border-slate-700/60 px-6 py-4">
        <div>
          <h1 className="text-lg font-bold tracking-tight">GitHub AI Engineer</h1>
          <p className="text-xs text-slate-500">MCP Host · Multi-server agent</p>
        </div>
        <button
          onClick={clearChat}
          className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-400 hover:border-slate-500 hover:text-slate-200"
        >
          Clear chat
        </button>
      </header>

      <StatusBar />

      <div className="flex flex-1 overflow-hidden">
        <main className="flex flex-1 flex-col overflow-hidden">
          <MessageList messages={messages} isLoading={isLoading} />

          {status && (
            <div className="border-t border-slate-800 px-4 py-2 text-xs text-slate-500">
              {status}
            </div>
          )}

          <form
            onSubmit={handleSubmit}
            className="border-t border-slate-700/60 p-4"
          >
            <div className="flex gap-2">
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Ask about code, security, architecture, GitHub…"
                disabled={isLoading}
                className="flex-1 rounded-xl border border-slate-700 bg-slate-900/60 px-4 py-3 text-sm text-slate-100 placeholder-slate-500 outline-none focus:border-blue-500 disabled:opacity-50"
              />
              <button
                type="submit"
                disabled={isLoading || !input.trim()}
                className="rounded-xl bg-blue-600 px-6 py-3 text-sm font-medium text-white hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-40"
              >
                Send
              </button>
            </div>
          </form>
        </main>

        <aside className="hidden w-80 flex-col border-l border-slate-700/60 lg:flex">
          <div className="border-b border-slate-700/60 px-4 py-3">
            <h2 className="text-sm font-semibold text-slate-300">Tool Logs</h2>
            <p className="text-xs text-slate-500">MCP tool invocations</p>
          </div>
          <div className="flex-1 overflow-hidden">
            <ToolLogPanel logs={toolLogs} />
          </div>
        </aside>
      </div>
    </div>
  );
}
