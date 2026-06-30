"""LLM service — OpenAI-compatible and Anthropic providers."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any, Literal

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from config.settings import Settings
from mcp_client import MCPToolInfo

logger = logging.getLogger(__name__)

Message = dict[str, Any]


class LLMService:
    """Unified interface for chat completions with tool calling."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.provider = settings.llm_provider

        if self.provider == "openai":
            if not settings.openai_api_key:
                raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
            self._openai = AsyncOpenAI(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url or None,
            )
        elif self.provider == "anthropic":
            if not settings.anthropic_api_key:
                raise ValueError("ANTHROPIC_API_KEY is required when LLM_PROVIDER=anthropic")
            self._anthropic = AsyncAnthropic(api_key=settings.anthropic_api_key)

    def mcp_tools_to_openai(self, tools: list[MCPToolInfo]) -> list[dict[str, Any]]:
        """Convert MCP tool schemas to OpenAI function-calling format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description[:1024] if t.description else t.name,
                    "parameters": t.input_schema,
                },
            }
            for t in tools
        ]

    def mcp_tools_to_anthropic(self, tools: list[MCPToolInfo]) -> list[dict[str, Any]]:
        """Convert MCP tool schemas to Anthropic tool format."""
        return [
            {
                "name": t.name,
                "description": t.description[:1024] if t.description else t.name,
                "input_schema": t.input_schema,
            }
            for t in tools
        ]

    async def chat(
        self,
        messages: list[Message],
        tools: list[MCPToolInfo],
    ) -> tuple[str | None, list[dict[str, Any]], Message | None]:
        """
        Run one LLM turn.

        Returns:
            (text_content, tool_calls, assistant_message_for_history)
        """
        if self.provider == "openai":
            return await self._chat_openai(messages, tools)
        return await self._chat_anthropic(messages, tools)

    async def _chat_openai(
        self,
        messages: list[Message],
        tools: list[MCPToolInfo],
    ) -> tuple[str | None, list[dict[str, Any]], Message | None]:
        kwargs: dict[str, Any] = {
            "model": self.settings.openai_model,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = self.mcp_tools_to_openai(tools)
            kwargs["tool_choice"] = "auto"

        response = await self._openai.chat.completions.create(**kwargs)
        choice = response.choices[0]
        msg = choice.message

        tool_calls: list[dict[str, Any]] = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls.append(
                    {
                        "id": tc.id,
                        "name": tc.function.name,
                        "arguments": json.loads(tc.function.arguments or "{}"),
                    }
                )

        assistant_msg: Message = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]

        return msg.content, tool_calls, assistant_msg

    async def _chat_anthropic(
        self,
        messages: list[Message],
        tools: list[MCPToolInfo],
    ) -> tuple[str | None, list[dict[str, Any]], Message | None]:
        system = ""
        anthropic_messages: list[dict[str, Any]] = []

        for m in messages:
            if m["role"] == "system":
                system = m.get("content", "")
            elif m["role"] == "user":
                anthropic_messages.append({"role": "user", "content": m.get("content", "")})
            elif m["role"] == "assistant":
                anthropic_messages.append({"role": "assistant", "content": m.get("content", "")})
            elif m["role"] == "tool":
                anthropic_messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": m.get("tool_call_id", ""),
                                "content": m.get("content", ""),
                            }
                        ],
                    }
                )

        kwargs: dict[str, Any] = {
            "model": self.settings.anthropic_model,
            "max_tokens": 8192,
            "messages": anthropic_messages,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = self.mcp_tools_to_anthropic(tools)

        response = await self._anthropic.messages.create(**kwargs)

        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []

        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    {
                        "id": block.id,
                        "name": block.name,
                        "arguments": block.input if isinstance(block.input, dict) else {},
                    }
                )

        content = "\n".join(text_parts) if text_parts else None
        assistant_msg: Message = {"role": "assistant", "content": content or ""}
        return content, tool_calls, assistant_msg

    async def stream_text(self, text: str, chunk_size: int = 20) -> AsyncIterator[str]:
        """Simulate streaming for final text responses (tool loop already ran)."""
        for i in range(0, len(text), chunk_size):
            yield text[i : i + chunk_size]
