"use client";

import type { ToolLogEntry } from "@/types";

interface ToolLogPanelProps {
  logs: ToolLogEntry[];
}

export function ToolLogPanel({ logs }: ToolLogPanelProps) {
  if (logs.length === 0) {
    return (
      <div className="flex h-full items-center justify-center p-4 text-sm text-slate-500">
        Tool executions will appear here
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2 overflow-y-auto p-3">
      {logs.map((log) => (
        <div
          key={log.id}
          className="rounded-lg border border-slate-700/60 bg-slate-900/60 p-3 text-xs"
        >
          <div className="mb-1 flex items-center gap-2">
            <StatusDot status={log.status} />
            <span className="font-mono font-medium text-blue-300">{log.name}</span>
          </div>
          {Object.keys(log.arguments).length > 0 && (
            <pre className="mb-1 overflow-x-auto rounded bg-slate-950/50 p-2 text-slate-400">
              {JSON.stringify(log.arguments, null, 2)}
            </pre>
          )}
          {log.result && (
            <details className="mt-1">
              <summary className="cursor-pointer text-slate-500 hover:text-slate-300">
                Result
              </summary>
              <pre className="mt-1 max-h-32 overflow-auto rounded bg-slate-950/50 p-2 text-green-400/80">
                {log.result}
              </pre>
            </details>
          )}
          {log.error && (
            <p className="mt-1 text-red-400">{log.error}</p>
          )}
        </div>
      ))}
    </div>
  );
}

function StatusDot({ status }: { status: ToolLogEntry["status"] }) {
  const colors = {
    running: "bg-yellow-400 animate-pulse",
    success: "bg-green-400",
    error: "bg-red-400",
  };
  return <span className={`inline-block h-2 w-2 rounded-full ${colors[status]}`} />;
}
