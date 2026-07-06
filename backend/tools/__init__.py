"""
tools/ — utility helpers for MCP tool argument building and result parsing.

This package is a convenience layer; all actual tool execution goes through
MCPClientManager.call_tool() which preserves the MCP protocol boundary.
"""

from __future__ import annotations

from typing import Any


def truncate(text: str, max_chars: int = 4000) -> str:
    """Truncate a string to max_chars, adding an indicator if cut."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n… [truncated, {len(text) - max_chars} chars omitted]"


def flatten_content_blocks(content: Any) -> str:
    """
    Flatten a list of MCP content blocks (or a plain value) to a string.

    Handles:
    - str             → returned as-is
    - list of dicts   → join .text / .data fields
    - anything else   → str()
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                parts.append(block.get("text") or block.get("data") or str(block))
            elif hasattr(block, "text"):
                parts.append(block.text)
            else:
                parts.append(str(block))
        return "\n".join(parts)
    return str(content)


def github_repo_args(owner: str, repo: str) -> dict[str, str]:
    """Return a standardized owner/repo argument dict for GitHub MCP tools."""
    return {"owner": owner, "repo": repo}


def safe_json_loads(raw: str) -> Any:
    """Parse JSON, returning the raw string on failure instead of raising."""
    import json
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw
