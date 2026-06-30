"use client";

import { useEffect, useState } from "react";
import { fetchHealth, fetchTools } from "@/lib/api";
import type { HealthStatus, MCPTool } from "@/types";

export function StatusBar() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [tools, setTools] = useState<MCPTool[]>([]);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    Promise.all([fetchHealth(), fetchTools()])
      .then(([h, t]) => {
        setHealth(h);
        setTools(t);
      })
      .catch(() => setHealth(null));
  }, []);

  return (
    <div className="border-b border-slate-700/60 bg-slate-900/40 px-4 py-2">
      <div className="flex items-center justify-between text-xs">
        <div className="flex items-center gap-4">
          <span className="font-semibold text-slate-300">MCP Status</span>
          {health ? (
            <>
              <Badge
                label="MCP"
                ok={health.mcp_connected}
                detail={`${health.tool_count} tools`}
              />
              <Badge label="LLM" ok={health.llm_configured} />
              {health.servers.map((s) => (
                <span
                  key={s}
                  className="rounded-full bg-slate-800 px-2 py-0.5 text-slate-400"
                >
                  {s}
                </span>
              ))}
            </>
          ) : (
            <span className="text-red-400">Backend offline</span>
          )}
        </div>
        <button
          onClick={() => setExpanded(!expanded)}
          className="text-slate-500 hover:text-slate-300"
        >
          {expanded ? "Hide tools" : `Show tools (${tools.length})`}
        </button>
      </div>
      {expanded && tools.length > 0 && (
        <div className="mt-2 max-h-32 overflow-y-auto">
          {tools.map((t) => (
            <div key={t.name} className="py-0.5 text-xs text-slate-500">
              <span className="font-mono text-slate-400">{t.name}</span>
              {t.server && (
                <span className="ml-2 text-slate-600">[{t.server}]</span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Badge({
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
        className={`inline-block h-1.5 w-1.5 rounded-full ${ok ? "bg-green-400" : "bg-red-400"}`}
      />
      <span className={ok ? "text-green-400/80" : "text-red-400/80"}>
        {label}
        {detail && <span className="ml-1 text-slate-500">({detail})</span>}
      </span>
    </span>
  );
}
