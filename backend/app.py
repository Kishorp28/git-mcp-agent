"""
FastAPI application — HTTP layer for the MCP Host.

Endpoints:
  GET  /health              — MCP + LLM status
  GET  /tools               — All discovered MCP tools
  GET  /tools/search        — Search tools by name/description
  POST /chat/stream         — SSE streaming chat (main endpoint)
  POST /chat                — Synchronous chat (testing / simple clients)
  POST /mcp/reconnect       — Reconnect to MCP servers
  GET  /sessions            — List active sessions
  GET  /sessions/{id}       — Get session history
  DELETE /sessions/{id}     — Delete a session
  POST /sessions/{id}/clear — Clear session history
"""

from __future__ import annotations

import json
import logging
import time
import uuid
import warnings
from contextlib import asynccontextmanager
from typing import Any

# Suppress noisy deprecation warnings from transitive dependencies
warnings.filterwarnings("ignore", category=DeprecationWarning, module=r"websockets\..*")
warnings.filterwarnings("ignore", category=DeprecationWarning, module=r"uvicorn\.protocols\..*")
warnings.filterwarnings("ignore", message=r".*authlib.*deprecated.*")

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from agent import GitHubAIAgent
from config.settings import get_settings
from mcp_client import MCPClientManager
from services.llm import LLMService
from utils.logging import setup_logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Singletons (initialized at startup)
# ---------------------------------------------------------------------------

_mcp_manager: MCPClientManager | None = None
_llm: LLMService | None = None

# ---------------------------------------------------------------------------
# Session store (in-memory; survives only for the server process lifetime)
# ---------------------------------------------------------------------------

class Session:
    """Holds conversation history for a single chat session."""

    def __init__(self, session_id: str) -> None:
        self.id = session_id
        self.history: list[dict[str, Any]] = []
        self.created_at = time.time()
        self.last_active = time.time()

    def touch(self) -> None:
        self.last_active = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "message_count": len(self.history),
            "created_at": self.created_at,
            "last_active": self.last_active,
        }


_sessions: dict[str, Session] = {}


def _get_or_create_session(session_id: str | None) -> Session:
    settings = get_settings()
    if session_id and session_id in _sessions:
        session = _sessions[session_id]
        session.touch()
        return session

    # Evict oldest sessions if over the limit
    if len(_sessions) >= settings.max_sessions:
        oldest_key = min(_sessions, key=lambda k: _sessions[k].last_active)
        del _sessions[oldest_key]

    new_id = session_id or str(uuid.uuid4())
    session = Session(new_id)
    _sessions[new_id] = session
    return session


def _evict_expired_sessions() -> None:
    settings = get_settings()
    cutoff = time.time() - settings.session_ttl_minutes * 60
    expired = [k for k, s in _sessions.items() if s.last_active < cutoff]
    for k in expired:
        del _sessions[k]
    if expired:
        logger.debug("Evicted %d expired sessions", len(expired))


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Connect MCP servers on startup; disconnect on shutdown."""
    global _mcp_manager, _llm

    settings = get_settings()
    setup_logging(settings.log_level)

    _mcp_manager = MCPClientManager(settings)
    try:
        await _mcp_manager.connect()
    except Exception:
        logger.exception("MCP connection failed — some tools may be unavailable")

    try:
        _llm = LLMService(settings)
        logger.info(
            "LLM configured: provider=%s model=%s",
            settings.llm_provider,
            settings.ollama_model,
        )
    except ValueError as exc:
        logger.warning("LLM not configured: %s", exc)
        _llm = None

    yield

    if _mcp_manager:
        await _mcp_manager.disconnect()


# ---------------------------------------------------------------------------
# App + middleware
# ---------------------------------------------------------------------------

app = FastAPI(
    title="GitHub AI Engineer",
    description="MCP-powered AI coding assistant for GitHub repositories",
    version="0.2.0",
    lifespan=lifespan,
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=32_000)
    session_id: str | None = Field(
        default=None,
        description="Reuse an existing session to continue the conversation. "
                    "Omit to start a new session.",
    )


class ChatResponse(BaseModel):
    response: str
    session_id: str


class HealthResponse(BaseModel):
    status: str
    mcp_connected: bool
    tool_count: int
    llm_configured: bool
    llm_provider: str | None
    llm_model: str | None
    servers: list[str]
    active_sessions: int


# ---------------------------------------------------------------------------
# Routes — Health & Tools
# ---------------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse, tags=["system"])
async def health() -> HealthResponse:
    """Return current health of MCP connections and LLM configuration."""
    s = get_settings()
    model = s.ollama_model if _llm else None

    return HealthResponse(
        status="ok",
        mcp_connected=_mcp_manager.is_connected if _mcp_manager else False,
        tool_count=len(_mcp_manager.tools) if _mcp_manager else 0,
        llm_configured=_llm is not None,
        llm_provider=s.llm_provider if _llm else None,
        llm_model=model,
        servers=_mcp_manager.server_names if _mcp_manager else [],
        active_sessions=len(_sessions),
    )


@app.get("/tools", tags=["tools"])
async def list_tools() -> list[dict[str, Any]]:
    """Return all MCP tools discovered from connected servers."""
    if not _mcp_manager:
        return []
    return [t.to_dict() for t in _mcp_manager.tools]


@app.get("/tools/search", tags=["tools"])
async def search_tools(
    q: str = Query(..., min_length=1, description="Search query"),
) -> list[dict[str, Any]]:
    """Search tools by name or description (case-insensitive substring match)."""
    if not _mcp_manager:
        return []
    query = q.lower()
    return [
        t.to_dict()
        for t in _mcp_manager.tools
        if query in t.name.lower() or query in (t.description or "").lower()
    ]


# ---------------------------------------------------------------------------
# Routes — Chat
# ---------------------------------------------------------------------------

@app.post("/chat/stream", tags=["chat"])
async def chat_stream(body: ChatRequest):
    """
    SSE streaming chat — yields Server-Sent Events consumed by the frontend.

    Event types:
      status        — agent status message
      message_start — assistant message is beginning
      message_delta — partial assistant text content
      message_end   — assistant message complete
      tool_start    — MCP tool about to be invoked
      tool_end      — MCP tool returned a result
      tool_error    — MCP tool raised an exception
      error         — agent-level error
      session       — session ID for this conversation
    """
    if not _llm or not _mcp_manager:
        raise HTTPException(
            status_code=503,
            detail="Agent not ready. Check /health for details.",
        )

    _evict_expired_sessions()
    session = _get_or_create_session(body.session_id)

    agent = GitHubAIAgent(get_settings(), _mcp_manager, _llm)

    async def event_generator():
        # Always emit the session ID first so the client can persist it
        yield {"event": "session", "data": json.dumps({"session_id": session.id})}

        async for event in agent.run(body.message, session.history):
            yield {"event": event.type, "data": json.dumps(event.data)}

    return EventSourceResponse(event_generator())


@app.post("/chat", response_model=ChatResponse, tags=["chat"])
async def chat_sync(body: ChatRequest) -> ChatResponse:
    """
    Synchronous (non-streaming) chat endpoint.
    Useful for testing, CLI clients, or simple integrations.
    """
    if not _llm or not _mcp_manager:
        raise HTTPException(
            status_code=503,
            detail="Agent not ready. Check /health for details.",
        )

    _evict_expired_sessions()
    session = _get_or_create_session(body.session_id)

    agent = GitHubAIAgent(get_settings(), _mcp_manager, _llm)
    final_parts: list[str] = []

    async for event in agent.run(body.message, session.history):
        if event.type == "message_delta":
            final_parts.append(event.data.get("content", ""))
        elif event.type == "error":
            raise HTTPException(
                status_code=500, detail=event.data.get("message")
            )

    return ChatResponse(response="".join(final_parts), session_id=session.id)


# ---------------------------------------------------------------------------
# Routes — Sessions
# ---------------------------------------------------------------------------

@app.get("/sessions", tags=["sessions"])
async def list_sessions() -> list[dict[str, Any]]:
    """List all active sessions with metadata."""
    _evict_expired_sessions()
    return [s.to_dict() for s in _sessions.values()]


@app.get("/sessions/{session_id}", tags=["sessions"])
async def get_session(session_id: str) -> dict[str, Any]:
    """Return the full conversation history for a session."""
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Strip system-role messages from the public history
    public_history = [
        m for m in session.history if m.get("role") != "system"
    ]
    return {**session.to_dict(), "history": public_history}


@app.delete("/sessions/{session_id}", tags=["sessions"])
async def delete_session(session_id: str) -> dict[str, str]:
    """Delete a session and its conversation history."""
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    del _sessions[session_id]
    return {"deleted": session_id}


@app.post("/sessions/{session_id}/clear", tags=["sessions"])
async def clear_session(session_id: str) -> dict[str, Any]:
    """Clear a session's conversation history without deleting the session."""
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    session.history = []
    session.touch()
    return session.to_dict()


# ---------------------------------------------------------------------------
# Routes — MCP management
# ---------------------------------------------------------------------------

@app.post("/mcp/reconnect", tags=["system"])
async def reconnect_mcp() -> dict[str, Any]:
    """Reconnect to all MCP servers (e.g. after configuration change)."""
    if not _mcp_manager:
        raise HTTPException(status_code=503, detail="MCP manager not initialized")

    await _mcp_manager.reconnect()
    return {
        "connected": _mcp_manager.is_connected,
        "tool_count": len(_mcp_manager.tools),
        "servers": _mcp_manager.server_names,
    }


@app.get("/mcp/tools-by-server", tags=["system"])
async def tools_by_server() -> dict[str, list[dict[str, Any]]]:
    """Return tools grouped by their originating MCP server."""
    if not _mcp_manager:
        return {}
    return {
        server: [t.to_dict() for t in tools]
        for server, tools in _mcp_manager.tools_by_server().items()
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os
    from pathlib import Path

    import uvicorn

    backend_dir = str(Path(__file__).resolve().parent)
    reload_enabled = os.getenv("UVICORN_RELOAD", "true").strip().lower() not in {
        "0", "false", "no"
    }
    uvicorn.run(
        "app:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        reload=reload_enabled,
        reload_dirs=[backend_dir],
        log_level="info",
    )
