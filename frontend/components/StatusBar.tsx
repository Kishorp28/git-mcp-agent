"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { fetchHealth, fetchTools, reconnectMCP, searchTools } from "@/lib/api";
import type { HealthStatus, MCPTool } from "@/types";

const POLL_INTERVAL_MS = 30_000;

export function StatusBar() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [tools, setTools] = useState<MCPTool[]>([]);
  const [toolSearch, setToolSearch] = useState("");
  const [filteredTools, setFilteredTools] = useState<MCPTool[]>([]);
  const [expanded, setExpanded] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(async (silent = false) => {
    if (!silent) setError(null);
    try {
      const [h, t] = await Promise.all([fetchHealth(), fetchTools()]);
      setHealth(h);
      setTools(t);
      setFilteredTools(t);
      setError(null);
    } catch {
      setHealth(null);
      if (!silent) setError("Backend unreachable");
    }
  }, []);

  // Initial load + polling
  useEffect(() => {
    load();
    pollRef.current = setInterval(() => load(true), POLL_INTERVAL_MS);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [load]);

  // Client-side search (debounced)
  useEffect(() => {
    if (!toolSearch.trim()) {
      setFilteredTools(tools);
      return;
    }
    const t = setTimeout(async () => {
      try {
        const results = await searchTools(toolSearch);
        setFilteredTools(results);
      } catch {
        const q = toolSearch.toLowerCase();
        setFilteredTools(
          tools.filter(
            (t) =>
              t.name.toLowerCase().includes(q) ||
              (t.description || "").toLowerCase().includes(q),
          ),
        );
      }
    }, 300);
    return () => clearTimeout(t);
  }, [toolSearch, tools]);

  const handleReconnect = async () => {
    setReconnecting(true);
    setError(null);
    try {
      await reconnectMCP();
      await load();
    } catch {
      setError("Reconnect failed");
    } finally {
      setReconnecting(false);
    }
  };

  const serverColors: Record<string, string> = {
    github: "text-purple-400 bg-purple-900/30",
    filesystem: "text-teal-400 bg-teal-900/30",
    git: "text-orange-400 bg-orange-900/30",
  };

  return (
    <div className="border-b border-slate-700/60 bg-slate-900/40">
      {/* Main row */}
      <div className="flex items-center justify-between px-4 py-2 text-xs">
        <div className="flex items-center gap-4 flex-wrap">
          <span className="font-semibold text-slate-300">MCP Status</span>

          {health ? (
            <>
              <StatusBadge
                label="MCP"
                ok={health.mcp_connected}
                detail={`${health.tool_count} tools`}
              />
              <StatusBadge label="LLM" ok={health.llm_configured} detail={health.llm_model ?? undefined} />
              {health.servers.map((s) => (
                <span
                  key={s}
                  className={`rounded-full px-2 py-0.5 font-medium ${
                    serverColors[s] ?? "bg-slate-800 text-slate-400"
                  }`}
                >
                  {s}
                </span>
              ))}
            </>
          ) : (
            <span className="flex items-center gap-1.5 text-red-400">
              <span className="inline-block h-1.5 w-1.5 rounded-full bg-red-400" />
              {error ?? "Backend offline"}
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          {/* Reconnect */}
          <button
            onClick={handleReconnect}
            disabled={reconnecting}
            className="flex items-center gap-1 rounded-lg border border-slate-700/60 px-2 py-1 text-slate-400 transition hover:border-slate-500 hover:text-slate-200 disabled:opacity-50"
            title="Reconnect MCP servers"
          >
            <svg
              className={`h-3 w-3 ${reconnecting ? "animate-spin" : ""}`}
              fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
            </svg>
            {reconnecting ? "Reconnecting…" : "Reconnect"}
          </button>

          {/* Expand/collapse tools */}
          <button
            onClick={() => setExpanded((v) => !v)}
            className="text-slate-500 transition hover:text-slate-300"
          >
            {expanded ? "Hide tools" : `Show ${tools.length} tools`}
          </button>
        </div>
      </div>

      {/* Tool list */}
      {expanded && (
        <div className="border-t border-slate-700/40 px-4 pb-3 pt-2">
          <input
            type="text"
            value={toolSearch}
            onChange={(e) => setToolSearch(e.target.value)}
            placeholder="Search tools…"
            className="mb-2 w-full rounded-lg border border-slate-700/60 bg-slate-800/60 px-3 py-1.5 text-xs text-slate-200 placeholder-slate-500 outline-none focus:border-blue-500/50"
          />
          <div className="max-h-36 overflow-y-auto space-y-0.5">
            {filteredTools.length === 0 ? (
              <p className="text-xs text-slate-500">No tools match</p>
            ) : (
              filteredTools.map((t) => (
                <div key={t.name} className="flex items-center gap-2 py-0.5 text-xs">
                  <span className="font-mono text-slate-300">{t.name}</span>
                  {t.server && (
                    <span
                      className={`rounded-full px-1.5 py-0 ${
                        serverColors[t.server] ?? "bg-slate-800 text-slate-400"
                      }`}
                    >
                      {t.server}
                    </span>
                  )}
                  {t.description && (
                    <span className="truncate text-slate-600">
                      {t.description}
                    </span>
                  )}
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function StatusBadge({
  label,
  ok,
  detail,
}: {
  label: string;
  ok: boolean;
  detail?: string;
}) {
  return (
    <span className="flex items-center gap-1">
      <span
        className={`inline-block h-1.5 w-1.5 rounded-full ${
          ok ? "bg-green-400" : "bg-red-400"
        }`}
      />
      <span className={ok ? "text-green-400/90" : "text-red-400/90"}>
        {label}
      </span>
      {detail && <span className="text-slate-500">({detail})</span>}
    </span>
  );
}
