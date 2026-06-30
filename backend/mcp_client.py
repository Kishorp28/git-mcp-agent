"""
MCP Client Manager — connects our application (MCP Host) to multiple MCP Servers.

Concept recap:
- **MCP Host**: This Python backend — orchestrates LLM + tool execution
- **MCP Client**: FastMCP's Client class — one logical client can wrap multiple servers
- **MCP Server**: External processes (GitHub, filesystem, git) that expose tools/resources
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from typing import Any

from fastmcp import Client

from config.settings import Settings

logger = logging.getLogger(__name__)


@dataclass
class MCPToolInfo:
    """Normalized tool metadata for the LLM and UI."""

    name: str
    description: str
    input_schema: dict[str, Any]
    server: str | None = None


@dataclass
class MCPClientManager:
    """
    Manages lifecycle of FastMCP Client connections to configured MCP servers.

    Builds a Claude-Desktop-style config dict and lets FastMCP handle
    subprocess spawning (stdio transport) for each server.
    """

    settings: Settings
    _client: Client | None = field(default=None, init=False, repr=False)
    _tools: list[MCPToolInfo] = field(default_factory=list, init=False, repr=False)

    def build_server_config(self) -> dict[str, Any]:
        """Build mcpServers configuration from application settings."""
        servers: dict[str, Any] = {}
        is_windows = sys.platform == "win32"

        if self.settings.github_mcp_enabled and self.settings.github_token:
            # Official GitHub MCP server (local via Docker — recommended)
            servers["github"] = {
                "command": "docker.exe" if is_windows else "docker",
                "args": [
                    "run",
                    "-i",
                    "--rm",
                    "-e",
                    "GITHUB_PERSONAL_ACCESS_TOKEN",
                    "ghcr.io/github/github-mcp-server",
                ],
                "env": {
                    "GITHUB_PERSONAL_ACCESS_TOKEN": self.settings.github_token,
                },
            }

        if self.settings.filesystem_mcp_enabled:
            allowed = str(self.settings.filesystem_allowed_path.resolve())
            servers["filesystem"] = {
                "command": "npx.cmd" if is_windows else "npx",
                "args": [
                    "-y",
                    "@modelcontextprotocol/server-filesystem",
                    allowed,
                ],
            }

        if self.settings.git_mcp_enabled:
            repo = str(self.settings.git_repository_path.resolve())
            servers["git"] = {
                "command": "uvx.exe" if is_windows else "uvx",
                "args": ["mcp-server-git", "--repository", repo],
            }

        return {"mcpServers": servers}

    async def connect(self) -> None:
        """Open MCP sessions to all configured servers and discover tools."""
        config = self.build_server_config()
        servers = config.get("mcpServers", {})

        if not servers:
            logger.warning("No MCP servers configured — agent will run without tools")
            self._tools = []
            return

        logger.info("Connecting to MCP servers: %s", list(servers.keys()))
        self._client = Client(config)
        await self._client.__aenter__()

        raw_tools = await self._client.list_tools()
        self._tools = [
            MCPToolInfo(
                name=t.name,
                description=t.description or "",
                input_schema=t.inputSchema or {"type": "object", "properties": {}},
                server=_infer_server_from_tool_name(t.name),
            )
            for t in raw_tools
        ]
        logger.info("Discovered %d MCP tools", len(self._tools))

    async def disconnect(self) -> None:
        """Close all MCP server connections."""
        if self._client is not None:
            await self._client.__aexit__(None, None, None)
            self._client = None
        self._tools = []

    @property
    def tools(self) -> list[MCPToolInfo]:
        return list(self._tools)

    @property
    def is_connected(self) -> bool:
        return self._client is not None

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Invoke an MCP tool by name and return structured result data."""
        if self._client is None:
            raise RuntimeError("MCP client is not connected")

        logger.debug("Calling MCP tool %s with args %s", name, arguments)
        result = await self._client.call_tool(name, arguments)

        if hasattr(result, "data"):
            return result.data
        if hasattr(result, "content") and result.content:
            parts = []
            for block in result.content:
                if hasattr(block, "text"):
                    parts.append(block.text)
                else:
                    parts.append(str(block))
            return "\n".join(parts) if parts else result
        return result

    async def list_resources(self) -> list[Any]:
        if self._client is None:
            return []
        return await self._client.list_resources()

    async def read_resource(self, uri: str) -> Any:
        if self._client is None:
            raise RuntimeError("MCP client is not connected")
        return await self._client.read_resource(uri)


def _infer_server_from_tool_name(name: str) -> str | None:
    """FastMCP prefixes multi-server tools as '{server}_{tool}'."""
    for prefix in ("github", "filesystem", "git"):
        if name.startswith(f"{prefix}_"):
            return prefix
    return None
