"""
AI Agent — orchestrates LLM reasoning with MCP tool execution.

This module is the brain of our MCP Host:
1. Receives user messages
2. Sends them to the LLM with available MCP tools
3. When the LLM requests a tool, invokes it via MCPClientManager
4. Feeds results back until the LLM produces a final answer
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from config.settings import Settings
from mcp_client import MCPClientManager
from prompts.system import SYSTEM_PROMPT
from services.llm import LLMService

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 15


@dataclass
class AgentEvent:
    """Structured events streamed to the frontend."""

    type: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_sse(self) -> str:
        return f"data: {json.dumps({'type': self.type, **self.data})}\n\n"


class GitHubAIAgent:
    """
    ReAct-style agent: LLM ↔ MCP tools loop until completion.

    The agent never calls GitHub/filesystem/git directly — every external
    action goes through MCP, preserving the protocol boundary.
    """

    def __init__(
        self,
        settings: Settings,
        mcp_manager: MCPClientManager,
        llm: LLMService,
    ) -> None:
        self.settings = settings
        self.mcp = mcp_manager
        self.llm = llm
        self._history: list[dict[str, Any]] = []

    def reset(self) -> None:
        self._history = []

    async def run(self, user_message: str) -> AsyncIterator[AgentEvent]:
        """Process a user message and yield streaming events."""
        try:
            self._history.append({"role": "user", "content": user_message})

            messages: list[dict[str, Any]] = [
                {"role": "system", "content": SYSTEM_PROMPT},
                *self._history,
            ]

            tools = self.mcp.tools
            yield AgentEvent("status", {"message": f"Connected — {len(tools)} MCP tools available"})

            for iteration in range(MAX_TOOL_ITERATIONS):
                content, tool_calls, assistant_msg = await self.llm.chat(messages, tools)

                if assistant_msg:
                    messages.append(assistant_msg)

                if not tool_calls:
                    final = content or "I couldn't generate a response."
                    self._history.append({"role": "assistant", "content": final})
                    yield AgentEvent("message_start", {})
                    async for chunk in self.llm.stream_text(final):
                        yield AgentEvent("message_delta", {"content": chunk})
                    yield AgentEvent("message_end", {})
                    return

                for tc in tool_calls:
                    tool_name = tc["name"]
                    tool_args = tc["arguments"]
                    tool_id = tc.get("id", tool_name)

                    yield AgentEvent(
                        "tool_start",
                        {"name": tool_name, "arguments": tool_args},
                    )

                    try:
                        result = await self.mcp.call_tool(tool_name, tool_args)
                        result_str = _serialize_tool_result(result)
                    except Exception as exc:
                        logger.exception("Tool %s failed", tool_name)
                        result_str = f"Error: {exc}"
                        yield AgentEvent(
                            "tool_error",
                            {"name": tool_name, "error": str(exc)},
                        )

                    yield AgentEvent(
                        "tool_end",
                        {"name": tool_name, "result": result_str[:2000]},
                    )

                    if self.llm.provider == "openai":
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_id,
                                "content": result_str,
                            }
                        )
                    else:
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_id,
                                "content": result_str,
                            }
                        )

                yield AgentEvent(
                    "status",
                    {"message": f"Tool round {iteration + 1} complete — reasoning…"},
                )

            yield AgentEvent(
                "error",
                {"message": f"Stopped after {MAX_TOOL_ITERATIONS} tool rounds."},
            )
        except Exception as exc:
            logger.exception("Agent run failed")
            yield AgentEvent("error", {"message": f"Agent Error: {exc}"})


def _serialize_tool_result(result: Any) -> str:
    if result is None:
        return "null"
    if isinstance(result, str):
        return result
    try:
        return json.dumps(result, indent=2, default=str)
    except (TypeError, ValueError):
        return str(result)
