"""
FastAPI application — HTTP layer for the MCP Host.

Exposes REST + SSE endpoints consumed by the Next.js frontend.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from agent import GitHubAIAgent
from config.settings import get_settings
from mcp_client import MCPClientManager
from services.llm import LLMService
from utils.logging import setup_logging

logger = logging.getLogger(__name__)

# Module-level singletons initialized at startup
_mcp_manager: MCPClientManager | None = None
_llm: LLMService | None = None


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
    except ValueError as exc:
        logger.warning("LLM not configured: %s", exc)
        _llm = None

    yield

    if _mcp_manager:
        await _mcp_manager.disconnect()


app = FastAPI(
    title="GitHub AI Engineer",
    description="MCP-powered AI coding assistant for GitHub repositories",
    version="0.1.0",
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


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=32000)


class HealthResponse(BaseModel):
    status: str
    mcp_connected: bool
    tool_count: int
    llm_configured: bool
    servers: list[str]


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    servers = list(_mcp_manager.build_server_config().get("mcpServers", {}).keys()) if _mcp_manager else []
    return HealthResponse(
        status="ok",
        mcp_connected=_mcp_manager.is_connected if _mcp_manager else False,
        tool_count=len(_mcp_manager.tools) if _mcp_manager else 0,
        llm_configured=_llm is not None,
        servers=servers,
    )


@app.get("/tools")
async def list_tools() -> list[dict[str, Any]]:
    if not _mcp_manager:
        return []
    return [
        {
            "name": t.name,
            "description": t.description,
            "server": t.server,
            "input_schema": t.input_schema,
        }
        for t in _mcp_manager.tools
    ]


@app.post("/chat")
async def chat_sync(body: ChatRequest) -> dict[str, str]:
    """Non-streaming chat endpoint (useful for testing)."""
    if not _llm or not _mcp_manager:
        raise HTTPException(status_code=503, detail="Agent not fully configured")

    agent = GitHubAIAgent(get_settings(), _mcp_manager, _llm)
    final = ""
    async for event in agent.run(body.message):
        if event.type == "message_delta":
            final += event.data.get("content", "")
        elif event.type == "error":
            raise HTTPException(status_code=500, detail=event.data.get("message"))
    return {"response": final}


@app.post("/chat/stream")
async def chat_stream(body: ChatRequest):
    """SSE streaming chat — frontend consumes Server-Sent Events."""
    if not _llm or not _mcp_manager:
        raise HTTPException(status_code=503, detail="Agent not fully configured")

    agent = GitHubAIAgent(get_settings(), _mcp_manager, _llm)

    async def event_generator():
        async for event in agent.run(body.message):
            yield {"event": event.type, "data": event.data}

    return EventSourceResponse(event_generator())


@app.post("/mcp/reconnect")
async def reconnect_mcp() -> dict[str, Any]:
    """Reconnect to MCP servers (e.g. after config change)."""
    global _mcp_manager
    if not _mcp_manager:
        raise HTTPException(status_code=503, detail="MCP manager not initialized")

    await _mcp_manager.disconnect()
    await _mcp_manager.connect()
    return {
        "connected": _mcp_manager.is_connected,
        "tool_count": len(_mcp_manager.tools),
    }
