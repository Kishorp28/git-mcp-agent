"""
MCP Client Manager - connects our application (MCP Host) to multiple MCP Servers.

Architecture:
- MCP Host: this Python backend orchestrates LLM + tool execution
- MCP Client: FastMCP's Client class wraps multiple servers
- MCP Server: external processes (GitHub, filesystem, git) expose tools/resources

Each server runs as a subprocess (stdio transport). FastMCP handles spawning.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import sys
import warnings
from dataclasses import dataclass, field
from typing import Any

# Suppress noisy deprecation warnings from FastMCP's transitive deps
_showwarning = warnings.showwarning
warnings.showwarning = lambda *args, **kwargs: None
try:
    from fastmcp import Client
finally:
    warnings.showwarning = _showwarning

from config.settings import Settings

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r"^[a-z][a-z0-9+.\-]*://", re.IGNORECASE)


# ---------------------------------------------------------------------------
# System dependency helpers
# ---------------------------------------------------------------------------

def _command_exists(command: str) -> bool:
    """Return True when an executable is available on PATH or venv/Scripts."""
    if shutil.which(command) is not None:
        return True
    from pathlib import Path
    venv_bin = Path(sys.prefix) / ("Scripts" if sys.platform == "win32" else "bin")
    return shutil.which(command, path=str(venv_bin)) is not None


def _docker_is_ready(command: str) -> bool:
    """Docker CLI can exist even when Docker Desktop/daemon is stopped."""
    if not _command_exists(command):
        return False
    try:
        subprocess.run(
            [command, "info"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return True
    except (OSError, subprocess.SubprocessError, FileNotFoundError):
        return False


def _resolve_uvx() -> str | None:
    """Find uvx executable on PATH or inside the active venv."""
    is_windows = sys.platform == "win32"
    uvx_command = "uvx.exe" if is_windows else "uvx"
    resolved = shutil.which(uvx_command)
    if resolved:
        return resolved
    from pathlib import Path
    venv_bin = Path(sys.prefix) / ("Scripts" if is_windows else "bin")
    return shutil.which(uvx_command, path=str(venv_bin))


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class MCPToolInfo:
    """Normalized tool metadata for the LLM and UI."""

    name: str
    description: str
    input_schema: dict[str, Any]
    server: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "server": self.server,
            "input_schema": self.input_schema,
        }


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

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
    _server_names: list[str] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        from cache import CacheManager
        from recovery import RecoveryEngine
        self.cache = CacheManager()
        self.recovery = RecoveryEngine()

    # ------------------------------------------------------------------
    # Config builder
    # ------------------------------------------------------------------

    def build_server_config(self) -> dict[str, Any]:
        """Build mcpServers configuration dict from application settings."""
        servers: dict[str, Any] = {}
        is_windows = sys.platform == "win32"

        # ---- GitHub MCP ----
        if self.settings.github_mcp_enabled:
            if not self.settings.github_token:
                logger.warning(
                    "Skipping GitHub MCP: GITHUB_PERSONAL_ACCESS_TOKEN is not set"
                )
            else:
                docker_cmd = "docker.exe" if is_windows else "docker"
                use_docker = (
                    self.settings.github_mcp_use_docker
                    and _docker_is_ready(docker_cmd)
                )
                if use_docker:
                    servers["github"] = {
                        "command": docker_cmd,
                        "args": [
                            "run", "-i", "--rm",
                            "-e", "GITHUB_PERSONAL_ACCESS_TOKEN",
                            "ghcr.io/github/github-mcp-server",
                        ],
                        "env": {
                            "GITHUB_PERSONAL_ACCESS_TOKEN": self.settings.github_token,
                        },
                    }
                else:
                    npx_cmd = "npx.cmd" if is_windows else "npx"
                    if _command_exists(npx_cmd):
                        servers["github"] = {
                            "command": npx_cmd,
                            "args": ["-y", "@modelcontextprotocol/server-github"],
                            "env": {
                                "GITHUB_PERSONAL_ACCESS_TOKEN": self.settings.github_token,
                            },
                        }
                    else:
                        logger.warning(
                            "Skipping GitHub MCP: Docker not ready and npx not found"
                        )

        # ---- Filesystem MCP ----
        if self.settings.filesystem_mcp_enabled:
            npx_cmd = "npx.cmd" if is_windows else "npx"
            if not _command_exists(npx_cmd):
                logger.warning("Skipping filesystem MCP: npx not found on PATH")
            else:
                allowed = str(
                    self.settings.resolve_project_path(
                        self.settings.filesystem_allowed_path
                    )
                )
                servers["filesystem"] = {
                    "command": npx_cmd,
                    "args": [
                        "-y",
                        "@modelcontextprotocol/server-filesystem",
                        allowed,
                    ],
                }

        # ---- Git MCP ----
        if self.settings.git_mcp_enabled:
            resolved_uvx = _resolve_uvx()
            if not resolved_uvx:
                logger.warning("Skipping Git MCP: uvx not found on PATH")
            else:
                repo = str(
                    self.settings.resolve_project_path(
                        self.settings.git_repository_path
                    )
                )
                servers["git"] = {
                    "command": resolved_uvx,
                    "args": ["mcp-server-git", "--repository", repo],
                }

        return {"mcpServers": servers}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Open MCP sessions to all configured servers and discover tools."""
        config = self.build_server_config()
        servers = config.get("mcpServers", {})
        self._server_names = list(servers.keys())

        if not servers:
            logger.warning(
                "No MCP servers configured — agent will run without tools"
            )
            self._tools = []
            return

        logger.info("Connecting to MCP servers: %s", list(servers.keys()))
        self._client = Client(config)
        await self._client.__aenter__()
        await self._refresh_tools()

    async def disconnect(self) -> None:
        """Close all MCP server connections cleanly."""
        if self._client is not None:
            try:
                await self._client.__aexit__(None, None, None)
            except Exception:  # noqa: BLE001
                logger.debug("Error during MCP disconnect (ignored)", exc_info=True)
            finally:
                self._client = None
        self._tools = []
        self._server_names = []

    async def reconnect(self) -> None:
        """Disconnect and reconnect to all MCP servers."""
        await self.disconnect()
        await self.connect()

    async def _refresh_tools(self) -> None:
        """Re-discover tools from connected servers."""
        if self._client is None:
            return
        try:
            raw_tools = await self._client.list_tools()
            only_server = (
                self._server_names[0] if len(self._server_names) == 1 else None
            )
            self._tools = [
                MCPToolInfo(
                    name=t.name,
                    description=t.description or "",
                    input_schema=(
                        t.inputSchema
                        if isinstance(t.inputSchema, dict)
                        else {"type": "object", "properties": {}}
                    ),
                    server=_infer_server(t.name) or only_server,
                )
                for t in raw_tools
            ]

            # Add custom Git tools not exposed by default mcp-server-git
            self._tools.append(
                MCPToolInfo(
                    name="git_git_pull",
                    description="Pull changes from a remote repository. Optionally specify remote and branch.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "remote": {
                                "type": "string",
                                "description": "The remote name (default: 'origin')",
                            },
                            "branch": {
                                "type": "string",
                                "description": "The branch name (default: active branch)",
                            },
                        },
                    },
                    server="git",
                )
            )
            self._tools.append(
                MCPToolInfo(
                    name="git_git_push",
                    description="Push committed changes to a remote repository. Optionally specify remote and branch.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "remote": {
                                "type": "string",
                                "description": "The remote name (default: 'origin')",
                            },
                            "branch": {
                                "type": "string",
                                "description": "The branch name (default: active branch)",
                            },
                        },
                    },
                    server="git",
                )
            )
            self._tools.append(
                MCPToolInfo(
                    name="git_git_fetch",
                    description="Fetch updates from a remote repository.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "remote": {
                                "type": "string",
                                "description": "The remote name (default: 'origin')",
                            },
                        },
                    },
                    server="git",
                )
            )

            logger.info("Discovered %d MCP tools", len(self._tools))
        except Exception:  # noqa: BLE001
            logger.exception("Failed to list MCP tools")
            self._tools = []

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def tools(self) -> list[MCPToolInfo]:
        return list(self._tools)

    @property
    def is_connected(self) -> bool:
        return self._client is not None

    @property
    def server_names(self) -> list[str]:
        return list(self._server_names)

    def tools_by_server(self) -> dict[str, list[MCPToolInfo]]:
        """Return tools grouped by their server name."""
        result: dict[str, list[MCPToolInfo]] = {}
        for t in self._tools:
            key = t.server or "unknown"
            result.setdefault(key, []).append(t)
        return result

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Invoke an MCP tool by name and return normalized result data."""
        if self._client is None:
            raise RuntimeError("MCP client is not connected")

        # Strip null/None arguments to avoid passing nulls to local tools
        arguments = {k: v for k, v in arguments.items() if v is not None}

        # Guard: prevent remote-URL arguments being passed to local Git tools
        guard_msg = self._validate_git_tool_args(name, arguments)
        if guard_msg:
            return guard_msg

        # Auto-inject absolute repo_path if missing/empty/relative/invalid in git tools
        if name.startswith("git_"):
            local_repo = str(self.settings.resolve_project_path(self.settings.git_repository_path))
            repo_path_val = arguments.get("repo_path")
            
            needs_override = False
            if not repo_path_val or repo_path_val in (".", "", None):
                needs_override = True
            else:
                try:
                    # Check if the path is outside the allowed project root
                    abs_repo_path = Path(repo_path_val).resolve()
                    if not str(abs_repo_path).startswith(str(self.settings.project_root)):
                        needs_override = True
                except Exception:
                    needs_override = True
                    
            if needs_override:
                arguments["repo_path"] = local_repo

        # Check Cache
        cached = self.cache.get(name, arguments)
        if cached is not None:
            status = "SUCCESS" if cached["ok"] else "FAILED"
            err_detail = f"\nerror={cached.get('error')}" if not cached["ok"] else ""
            args_formatted = "\n  ".join(f"{k}={v}" for k, v in arguments.items())
            logger.info(
                "CACHE HIT:\ntool=%s\nargs={\n  %s\n}\ncached_status=%s%s",
                name,
                args_formatted,
                status,
                err_detail
            )
            if cached["ok"]:
                return cached["data"]
            else:
                raise RuntimeError(cached["error"])

        logger.debug("Calling MCP tool %s args=%s", name, arguments)
        result: Any
        try:
            if name in ("git_git_pull", "git_git_push", "git_git_fetch"):
                result = await self._call_custom_git_tool(name, arguments)
            else:
                raw_result = await self._client.call_tool(name, arguments)
                result = _normalize_result(raw_result)

            # Cache successful results
            self.cache.set(name, arguments, result, ok=True)
            
            # Invalidate any related query caches if this was a mutating tool
            self.cache.invalidate_on_mutation(name, arguments)
            
            return result

        except Exception as exc:  # noqa: BLE001
            # Run failure through Recovery Engine
            strategy = await self.recovery.analyze_failure(name, arguments, str(exc))
            
            # Cache failure
            self.cache.set(name, arguments, strategy.description, ok=False)
            
            raise RuntimeError(strategy.description) from exc

    async def _call_custom_git_tool(self, name: str, arguments: dict[str, Any]) -> str:
        import asyncio
        repo_path = str(self.settings.resolve_project_path(self.settings.git_repository_path))
        remote = arguments.get("remote") or "origin"
        branch = arguments.get("branch")
        
        cmd = ["git"]
        if name == "git_git_pull":
            cmd.append("pull")
        elif name == "git_git_push":
            cmd.append("push")
        elif name == "git_git_fetch":
            cmd.append("fetch")
            
        cmd.append(remote)
        if branch:
            cmd.append(branch)
            
        logger.info("Executing custom git command: %s in %s", cmd, repo_path)
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=repo_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            
            out_str = stdout.decode("utf-8", errors="replace")
            err_str = stderr.decode("utf-8", errors="replace")
            
            result_parts = []
            if out_str.strip():
                result_parts.append(out_str)
            if err_str.strip():
                result_parts.append(err_str)
                
            res = "\n".join(result_parts)
            if proc.returncode != 0:
                return f"Git command failed (exit code {proc.returncode}):\n{res}"
            return res if res.strip() else "Git command completed successfully."
        except Exception as exc:
            return f"Failed to execute git command: {exc}"

    # ------------------------------------------------------------------
    # Resources
    # ------------------------------------------------------------------

    async def list_resources(self) -> list[Any]:
        if self._client is None:
            return []
        try:
            return await self._client.list_resources()
        except Exception:  # noqa: BLE001
            logger.debug("list_resources failed", exc_info=True)
            return []

    async def read_resource(self, uri: str) -> Any:
        if self._client is None:
            raise RuntimeError("MCP client is not connected")
        return await self._client.read_resource(uri)

    # ------------------------------------------------------------------
    # Internal validators
    # ------------------------------------------------------------------

    def _validate_git_tool_args(
        self, name: str, arguments: dict[str, Any]
    ) -> str | None:
        """
        Git MCP works on a local checkout only.
        Return an error string if a remote URL is passed as an argument.
        """
        if not name.startswith("git_"):
            return None

        remote_values = [
            v
            for v in arguments.values()
            if isinstance(v, str) and _URL_RE.match(v.strip())
        ]
        if not remote_values:
            return None

        local_repo = self.settings.resolve_project_path(
            self.settings.git_repository_path
        )
        logger.warning(
            "Blocked Git MCP call %s with remote URL: %s", name, remote_values[0]
        )
        return (
            "Git MCP tools can only inspect a local repository checkout, "
            f"not a remote URL. The configured local repository is: {local_repo}. "
            "To inspect a GitHub repository remotely, use the GitHub MCP server instead."
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _infer_server(tool_name: str) -> str | None:
    """
    Infer which server a tool belongs to from its name prefix.
    FastMCP uses '{server}_{tool}' naming for multi-server configs.
    """
    for prefix in ("github", "filesystem", "git"):
        if tool_name.startswith(f"{prefix}_") or tool_name == prefix:
            return prefix
    return None


def _normalize_result(result: Any) -> Any:
    """
    Normalize FastMCP tool call results into plain Python objects.

    FastMCP returns objects with .content (list of blocks) or .data.
    We flatten them into a string or pass through plain values.
    """
    if result is None:
        return None

    # Prefer explicit .data attribute (some FastMCP versions)
    if hasattr(result, "data") and result.data is not None:
        return result.data

    # Content blocks (TextContent, ImageContent, etc.)
    if hasattr(result, "content") and result.content:
        parts: list[str] = []
        for block in result.content:
            if hasattr(block, "text") and block.text is not None:
                parts.append(block.text)
            elif hasattr(block, "data") and block.data is not None:
                parts.append(str(block.data))
            else:
                parts.append(str(block))
        return "\n".join(parts) if parts else str(result)

    # Plain string/dict/list — return as-is
    if isinstance(result, (str, dict, list, int, float, bool)):
        return result

    return str(result)
