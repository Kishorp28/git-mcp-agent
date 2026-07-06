"use client";

import { useState, useMemo } from "react";
import type { ToolLogEntry } from "@/types";

interface ToolLogPanelProps {
  logs: ToolLogEntry[];
  onClear?: () => void;
}

function StatusDot({ status }: { status: ToolLogEntry["status"] }) {
  const cls = {
    running: "bg-yellow-400 animate-pulse",
    success: "bg-green-400",
    error: "bg-red-400",
  }[status];
  return <span className={`inline-block h-2 w-2 shrink-0 rounded-full ${cls}`} />;
}

function formatDuration(ms?: number): string {
  if (ms == null) return "";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function ToolEntry({ log }: { log: ToolLogEntry }) {
  const [open, setOpen] = useState(false);
  const hasArgs = Object.keys(log.arguments).length > 0;

  return (
    <div className="rounded-lg border border-slate-700/50 bg-slate-900/60 text-xs overflow-hidden">
      {/* Header row */}
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-slate-800/60 transition-colors"
      >
        <StatusDot status={log.status} />
        <span className="flex-1 truncate font-mono font-medium text-blue-300">
          {log.name}
        </span>
        {log.durationMs != null && (
          <span className="shrink-0 text-slate-500">
            {formatDuration(log.durationMs)}
          </span>
        )}
        <svg
          className={`h-3 w-3 shrink-0 text-slate-500 transition-transform ${open ? "rotate-180" : ""}`}
          fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {/* Expanded content */}
      {open && (
        <div className="border-t border-slate-700/40 px-3 pb-3 pt-2 space-y-2">
          {/* Arguments */}
          {hasArgs && (
            <div>
              <p className="mb-1 text-slate-500">Arguments</p>
              <pre className="overflow-x-auto rounded bg-slate-950/60 p-2 text-slate-400 leading-relaxed">
                {JSON.stringify(log.arguments, null, 2)}
              </pre>
            </div>
          )}

          {/* Result */}
          {log.result && (
            <div>
              <p className="mb-1 text-slate-500">Result</p>
              <pre className="max-h-40 overflow-auto rounded bg-slate-950/60 p-2 text-green-400/90 leading-relaxed">
                {log.result}
              </pre>
            </div>
          )}

          {/* Error */}
          {log.error && (
            <div>
              <p className="mb-1 text-slate-500">Error</p>
              <p className="rounded bg-red-950/40 p-2 text-red-400">{log.error}</p>
            </div>
          )}

          {/* Timestamp */}
          <p className="text-slate-600">
            {log.timestamp.toLocaleTimeString()}
          </p>
        </div>
      )}
    </div>
  );
}

export function ToolLogPanel({ logs, onClear }: ToolLogPanelProps) {
  const [search, setSearch] = useState("");

  const filtered = useMemo(() => {
    if (!search.trim()) return logs;
    const q = search.toLowerCase();
    return logs.filter(
      (l) =>
        l.name.toLowerCase().includes(q) ||
        JSON.stringify(l.arguments).toLowerCase().includes(q),
    );
  }, [logs, search]);

  const counts = useMemo(
    () => ({
      total: logs.length,
      success: logs.filter((l) => l.status === "success").length,
      error: logs.filter((l) => l.status === "error").length,
      running: logs.filter((l) => l.status === "running").length,
    }),
    [logs],
  );

  if (logs.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 p-4 text-center">
        <svg className="h-8 w-8 text-slate-700" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M11.42 15.17L17.25 21A2.652 2.652 0 0021 17.25l-5.877-5.877M11.42 15.17l2.496-3.03c.317-.384.74-.626 1.208-.766M11.42 15.17l-4.655 5.653a2.548 2.548 0 11-3.586-3.586l6.837-5.63m5.108-.233c.55-.164 1.163-.188 1.743-.14a4.5 4.5 0 004.486-6.336l-3.276 3.277a3.004 3.004 0 01-2.25-2.25l3.276-3.276a4.5 4.5 0 00-6.336 4.486c.091 1.076-.071 2.264-.904 2.95l-.102.085m-1.745 1.437L5.909 7.5H4.5L2.25 3.75l1.5-1.5L7.5 4.5v1.409l4.26 4.26m-1.745 1.437l1.745-1.437m6.615 8.206L15.75 15.75M4.867 19.125h.008v.008h-.008v-.008z" />
        </svg>
        <p className="text-sm text-slate-500">Tool executions will appear here</p>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      {/* Stats bar */}
      <div className="flex items-center gap-3 border-b border-slate-700/40 px-3 py-2 text-xs">
        <span className="text-slate-400">{counts.total} calls</span>
        {counts.success > 0 && (
          <span className="text-green-400">{counts.success} ok</span>
        )}
        {counts.error > 0 && (
          <span className="text-red-400">{counts.error} err</span>
        )}
        {counts.running > 0 && (
          <span className="animate-pulse text-yellow-400">{counts.running} running</span>
        )}
        {onClear && (
          <button
            onClick={onClear}
            className="ml-auto text-slate-500 hover:text-slate-300 transition-colors"
          >
            Clear
          </button>
        )}
      </div>

      {/* Search */}
      <div className="border-b border-slate-700/40 px-3 py-2">
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Filter tools…"
          className="w-full rounded-lg border border-slate-700/60 bg-slate-800/60 px-3 py-1.5 text-xs text-slate-200 placeholder-slate-500 outline-none focus:border-blue-500/50"
        />
      </div>

      {/* Entries */}
      <div className="flex flex-1 flex-col gap-2 overflow-y-auto p-3">
        {filtered.length === 0 ? (
          <p className="text-center text-xs text-slate-500 mt-4">
            No tools match &ldquo;{search}&rdquo;
          </p>
        ) : (
          [...filtered].reverse().map((log) => (
            <ToolEntry key={log.id} log={log} />
          ))
        )}
      </div>
    </div>
  );
}
