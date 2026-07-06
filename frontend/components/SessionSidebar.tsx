"use client";

import { useCallback, useEffect, useState } from "react";
import { deleteSession, fetchSessions } from "@/lib/api";
import type { SessionInfo } from "@/types";

interface SessionSidebarProps {
  currentSessionId: string | null;
  onSelectSession: (id: string) => void;
  onNewChat: () => void;
}

function formatRelative(ts: number): string {
  const diff = Date.now() - ts * 1000;
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export function SessionSidebar({
  currentSessionId,
  onSelectSession,
  onNewChat,
}: SessionSidebarProps) {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [loading, setLoading] = useState(true);

  const loadSessions = useCallback(async () => {
    try {
      const data = await fetchSessions();
      // Sort newest first
      setSessions(
        [...data].sort((a, b) => b.last_active - a.last_active),
      );
    } catch {
      // backend may not be ready yet
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSessions();
  }, [loadSessions, currentSessionId]);

  const handleDelete = async (
    e: React.MouseEvent,
    sessionId: string,
  ) => {
    e.stopPropagation();
    try {
      await deleteSession(sessionId);
      setSessions((prev) => prev.filter((s) => s.id !== sessionId));
      if (sessionId === currentSessionId) onNewChat();
    } catch {
      // ignore
    }
  };

  return (
    <div className="flex h-full w-56 flex-col border-r border-slate-700/60 bg-slate-950/60">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-700/60 px-3 py-3">
        <span className="text-sm font-semibold text-slate-300">Chats</span>
        <button
          onClick={onNewChat}
          className="flex items-center gap-1 rounded-lg border border-slate-700 px-2 py-1 text-xs text-slate-400 transition hover:border-slate-500 hover:text-slate-200"
          title="New chat"
        >
          <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
          </svg>
          New
        </button>
      </div>

      {/* Session list */}
      <div className="flex flex-1 flex-col overflow-y-auto py-1">
        {loading ? (
          <div className="flex items-center justify-center py-8">
            <div className="h-4 w-4 animate-spin rounded-full border-2 border-slate-600 border-t-blue-400" />
          </div>
        ) : sessions.length === 0 ? (
          <p className="px-3 py-4 text-xs text-slate-500">No sessions yet</p>
        ) : (
          sessions.map((session) => {
            const isActive = session.id === currentSessionId;
            return (
              <button
                key={session.id}
                onClick={() => onSelectSession(session.id)}
                className={`group flex w-full items-center justify-between gap-2 px-3 py-2.5 text-left transition-colors ${
                  isActive
                    ? "bg-blue-600/20 text-slate-200"
                    : "text-slate-400 hover:bg-slate-800/60 hover:text-slate-200"
                }`}
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate text-xs font-medium">
                    {session.id.slice(0, 8)}…
                  </p>
                  <p className="text-xs text-slate-600">
                    {session.message_count} msg · {formatRelative(session.last_active)}
                  </p>
                </div>

                {/* Delete button */}
                <button
                  onClick={(e) => handleDelete(e, session.id)}
                  className="shrink-0 rounded p-0.5 text-slate-600 opacity-0 transition group-hover:opacity-100 hover:bg-red-900/40 hover:text-red-400"
                  title="Delete session"
                  aria-label="Delete session"
                >
                  <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}
