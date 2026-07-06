"""
LLM service for Ollama.

Handles:
- Tool schema conversion (MCP → OpenAI format)
- Message history sanitization (lowercase tool names, role normalization)
- Rate-limit pacing via configurable delay
- Simulated streaming for final responses
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import AsyncIterator
from typing import Any

from openai import AsyncOpenAI, RateLimitError as OpenAIRateLimitError

from config.settings import Settings
from mcp_client import MCPToolInfo

logger = logging.getLogger(__name__)

Message = dict[str, Any]

# Maximum message history turns kept per LLM call (system prompt excluded)
_MAX_HISTORY_TURNS = 20


class LLMService:
    """Interface for chat completions with tool calling using local Ollama."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.provider = settings.llm_provider
        self.call_count = 0
        self._request_lock = asyncio.Lock()
        self._last_request_at: float = 0.0

        if self.provider == "ollama":
            self._client = AsyncOpenAI(
                api_key="ollama",  # Ollama doesn't validate API key but SDK requires it
                base_url=settings.ollama_base_url,
                max_retries=0,
                timeout=300.0,
            )
        else:
            raise ValueError(
                f"Unknown LLM_PROVIDER '{self.provider}'. "
                "Choose 'ollama'."
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[Message],
        tools: list[MCPToolInfo],
    ) -> tuple[str | None, list[dict[str, Any]], Message | None]:
        """
        Run one LLM turn.

        Returns:
            (text_content, tool_calls, assistant_message_for_history)

        The assistant_message_for_history is None only on catastrophic failure.
        """
        # Trim history to avoid token overruns; always keep system prompt
        messages = _trim_messages(messages)

        # Estimate prompt tokens and increment call count
        char_count = sum(len(str(m.get("content") or "")) for m in messages)
        estimated_tokens = char_count // 4
        
        self.call_count += 1
        model_name = self.settings.ollama_model
        logger.info(
            "LLM call #%d | model=%s | estimated_prompt_tokens=%d",
            self.call_count,
            model_name,
            estimated_tokens,
        )

        # Ensure tool names are lowercase so they match our schema
        lowercase_to_original = {t.name.lower(): t.name for t in tools}
        sanitized = _sanitize_tool_call_names(messages)

        if self.provider == "ollama":
            content, tool_calls, assistant_msg = await self._chat_ollama(
                sanitized, tools
            )
        else:
            raise ValueError(f"Unsupported LLM provider: {self.provider}")

        # Restore original casing so MCP client can route calls correctly
        for tc in tool_calls:
            low = tc["name"].lower()
            if low in lowercase_to_original:
                tc["name"] = lowercase_to_original[low]

        return content, tool_calls, assistant_msg

    async def stream_text(
        self, text: str, chunk_size: int = 20
    ) -> AsyncIterator[str]:
        """Yield text in small chunks to simulate streaming."""
        for i in range(0, len(text), chunk_size):
            yield text[i : i + chunk_size]
            await asyncio.sleep(0)  # yield control to the event loop

    # ------------------------------------------------------------------
    # Schema converters
    # ------------------------------------------------------------------

    def mcp_tools_to_openai(
        self, tools: list[MCPToolInfo]
    ) -> list[dict[str, Any]]:
        """Convert MCP tool schemas to OpenAI function-calling format."""
        result = []
        for t in tools:
            schema = _slim_schema(t.input_schema)
            result.append(
                {
                    "type": "function",
                    "function": {
                        "name": t.name.lower(),
                        "description": (t.description or t.name)[:256],
                        "parameters": schema,
                    },
                }
            )
        return result

    # ------------------------------------------------------------------
    # Rate-limit pacing
    # ------------------------------------------------------------------

    async def _pace_request(self) -> None:
        delay = max(0.0, self.settings.llm_request_delay_seconds)
        async with self._request_lock:
            if delay:
                elapsed = time.monotonic() - self._last_request_at
                wait = delay - elapsed
                if wait > 0:
                    await asyncio.sleep(wait)
            self._last_request_at = time.monotonic()

    # ------------------------------------------------------------------
    # Ollama provider
    # ------------------------------------------------------------------

    async def _chat_ollama(
        self,
        messages: list[Message],
        tools: list[MCPToolInfo],
    ) -> tuple[str | None, list[dict[str, Any]], Message | None]:
        kwargs: dict[str, Any] = {
            "model": self.settings.ollama_model,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = self.mcp_tools_to_openai(tools)
            kwargs["tool_choice"] = "auto"

        await self._pace_request()
        for attempt in range(4):
            try:
                response = await self._client.chat.completions.create(**kwargs)
                break
            except Exception as exc:
                exc_msg = str(exc).lower()
                is_rate_limit = (
                    isinstance(exc, OpenAIRateLimitError)
                    or "rate limit" in exc_msg
                    or "429" in exc_msg
                    or "too many requests" in exc_msg
                )
                is_retryable = (
                    is_rate_limit
                    or "timeout" in exc_msg
                    or "connection" in exc_msg
                    or "read error" in exc_msg
                    or "readerror" in exc_msg
                    or "connecterror" in exc_msg
                    or "connect error" in exc_msg
                )
                if is_retryable and attempt < 3:
                    import random
                    sleep_time = min(2 ** (attempt + 1) + random.uniform(0.5, 2.0), 60.0)
                    logger.warning("Ollama request failed, retrying in %.2f seconds (attempt %d/3)... Error: %s", sleep_time, attempt + 1, exc)
                    await asyncio.sleep(sleep_time)
                    continue
                if is_rate_limit or is_retryable:
                    raise RuntimeError(
                        f"Ollama request failed: {exc}. Please wait a few seconds and try again."
                    ) from exc
                raise exc
        if not response or not response.choices:
            raise RuntimeError("Ollama returned an empty response with no choices.")
        choice = response.choices[0]
        msg = choice.message
        if not msg:
            raise RuntimeError("Ollama returned a choice with no message content.")

        tool_calls: list[dict[str, Any]] = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                args = _parse_tool_arguments(tc.function.arguments)
                tool_calls.append(
                    {
                        "id": tc.id,
                        "name": tc.function.name,
                        "arguments": args,
                    }
                )
        elif msg.content:
            # Fallback: Parse tool calls from plain text content if native tool calling failed
            tool_calls = _extract_tool_calls_from_text(msg.content, tools)

        # Build the assistant message for history (with tool_calls if present)
        assistant_msg: Message = {
            "role": "assistant",
            "content": msg.content or "",
        }
        if tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": json.dumps(tc["arguments"]),
                    },
                }
                for tc in tool_calls
            ]

        return msg.content, tool_calls, assistant_msg


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slim_schema(schema: Any) -> dict[str, Any]:
    """
    Strip verbose JSON Schema fields that inflate token counts.

    Keeps: type, properties (type + description per prop), required, additionalProperties.
    Drops: $defs, $schema, examples, default, allOf/anyOf/oneOf nesting.

    The `required` array is preserved exactly — models use it to know which
    arguments they must supply. Dropping it is what causes empty-arg tool calls.
    """
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}}

    slimmed: dict[str, Any] = {"type": schema.get("type", "object")}

    raw_props = schema.get("properties", {})
    required = schema.get("required", []) if isinstance(schema.get("required"), list) else []
    
    if isinstance(raw_props, dict):
        slim_props: dict[str, Any] = {}
        for name, prop in raw_props.items():
            if not isinstance(prop, dict):
                slim_props[name] = {"type": ["string", "null"] if name not in required else "string"}
                continue
            entry: dict[str, Any] = {}
            if "type" in prop:
                val_type = prop["type"]
                if name not in required:
                    if isinstance(val_type, list):
                        entry["type"] = val_type + ["null"] if "null" not in val_type else val_type
                    elif isinstance(val_type, str):
                        entry["type"] = [val_type, "null"]
                else:
                    entry["type"] = val_type
            if "description" in prop:
                entry["description"] = prop["description"][:120]
            if "enum" in prop:
                entry["enum"] = prop["enum"]
            if "items" in prop:
                # Keep array item type info (but not nested $refs)
                items = prop["items"]
                entry["items"] = {"type": items.get("type", "string")} if isinstance(items, dict) else items
            slim_props[name] = entry
        slimmed["properties"] = slim_props

    # CRITICAL: always preserve required — this tells the LLM which args it must fill
    if "required" in schema and isinstance(schema["required"], list):
        slimmed["required"] = schema["required"]

    if "additionalProperties" in schema:
        slimmed["additionalProperties"] = schema["additionalProperties"]

    return slimmed


def _trim_messages(messages: list[Message]) -> list[Message]:
    """
    Keep the system prompt plus the last N non-system turns.
    Prevents context-window overruns on long conversations.
    """
    system_msgs = [m for m in messages if m.get("role") == "system"]
    other_msgs = [m for m in messages if m.get("role") != "system"]
    if len(other_msgs) > _MAX_HISTORY_TURNS:
        other_msgs = other_msgs[-_MAX_HISTORY_TURNS:]
    return system_msgs + other_msgs


def _sanitize_tool_call_names(messages: list[Message]) -> list[Message]:
    """
    Lowercase all tool call function names in the message history.
    Some models return mixed-case names; our schema uses lowercase.
    """
    sanitized: list[Message] = []
    for m in messages:
        if "tool_calls" not in m or not m["tool_calls"]:
            sanitized.append(m)
            continue
        m_copy = dict(m)
        tc_list = []
        for tc in m["tool_calls"]:
            tc_copy = dict(tc)
            if "function" in tc_copy and isinstance(tc_copy["function"], dict):
                func = dict(tc_copy["function"])
                func["name"] = func.get("name", "").lower()
                tc_copy["function"] = func
            tc_list.append(tc_copy)
        m_copy["tool_calls"] = tc_list
        sanitized.append(m_copy)
    return sanitized


def _parse_tool_arguments(raw_args: str | dict[str, Any] | None) -> dict[str, Any]:
    """Robustly parse tool arguments JSON returned by the model."""
    if not raw_args:
        return {}
    if isinstance(raw_args, dict):
        return raw_args
        
    s = raw_args.strip()
    if not s:
        return {}
        
    # Unescape if it was doubly stringified
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        try:
            unquoted = json.loads(f'[{s}]')[0]
            if isinstance(unquoted, dict):
                return unquoted
            if isinstance(unquoted, str):
                s = unquoted.strip()
        except Exception:
            pass

    # Clean markdown formatting if model wrapped JSON in codeblocks
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z0-9]*\n", "", s)
        s = re.sub(r"\n```$", "", s)
        s = s.strip()

    try:
        return json.loads(s)
    except json.JSONDecodeError:
        # Fallback 1: Try fixing single quotes
        try:
            fixed = re.sub(r"'([^']*)'", r'"\1"', s)
            return json.loads(fixed)
        except Exception:
            pass
            
        # Fallback 2: Try simple regex key-value extraction if parsing fails entirely
        try:
            extracted = {}
            for k, v in re.findall(r'"(\w+)":\s*"([^"]*)"', s):
                extracted[k] = v
            if extracted:
                return extracted
        except Exception:
            pass

    return {}


def _extract_tool_calls_from_text(content: str, tools: list[MCPToolInfo]) -> list[dict[str, Any]]:
    """
    Search for structured tool calls embedded in plain text content.
    Matches JSON-like blocks referencing known tool names.
    """
    if not content:
        return []
        
    extracted: list[dict[str, Any]] = []
    tool_names = {t.name.lower(): t.name for t in tools}
    
    # Pattern 1: Look for JSON blocks in text
    json_blocks = re.findall(r"(\{.*?\})", content, re.DOTALL)
    for block in json_blocks:
        try:
            data = json.loads(block.strip())
            name = data.get("name") or data.get("tool") or data.get("function")
            if isinstance(name, str) and name.lower() in tool_names:
                args = data.get("arguments") or data.get("args") or data.get("parameters") or {}
                extracted.append({
                    "id": f"call_{len(extracted)}_{int(time.time())}",
                    "name": tool_names[name.lower()],
                    "arguments": args if isinstance(args, dict) else _parse_tool_arguments(str(args))
                })
        except Exception:
            continue
            
    return extracted
