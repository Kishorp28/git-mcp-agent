"""
AI Agent — orchestrates LLM reasoning with MCP tool execution.

ReAct-style loop:
1. Receive user message
2. Send to LLM with available MCP tools
3. Before executing a tool call: validate required arguments are non-empty.
   If invalid → inject a corrective message and retry (up to MAX_VALIDATE_RETRIES).
4. Execute the tool via MCPClientManager and feed results back.
5. Repeat until the LLM produces a final text answer.
6. Stream all events to the frontend throughout.

Session-level conversation history is managed by the caller (app.py).
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from config.settings import Settings
from graph import TaskGraph
from mcp_client import MCPClientManager
from planner import Planner
from prompts.system import build_system_prompt, unavailable_tool_message
from services.llm import LLMService

logger = logging.getLogger(__name__)


@dataclass
class AgentEvent:
    """Structured events streamed to the frontend via SSE."""

    type: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_sse(self) -> str:
        return f"data: {json.dumps({'type': self.type, **self.data})}\n\n"


# ---------------------------------------------------------------------------
# Tool argument validation
# ---------------------------------------------------------------------------

# Fields that must be non-empty for mutating GitHub tools.
# The key is a substring matched against the tool name (lowercase).
_REQUIRED_ARGS: dict[str, list[str]] = {
    "create_or_update_file": ["owner", "repo", "path", "content", "message"],
    "create_issue":          ["owner", "repo", "title"],
    "create_pull_request":   ["owner", "repo", "title", "head", "base"],
    "update_issue":          ["owner", "repo", "issue_number"],
    "create_release":        ["owner", "repo", "tag_name"],
    "delete_file":           ["owner", "repo", "path", "message", "sha"],
    "fork_repository":       ["owner", "repo"],
    "create_branch":         ["owner", "repo", "branch"],
    "merge_pull_request":    ["owner", "repo", "pull_number"],
    "add_pull_request_review_comment": ["owner", "repo", "pull_number", "body"],
    "create_repository":     ["name"],
}

# Retries after the first rejected tool call (1 = one correction attempt, then ask user)
_MAX_VALIDATE_RETRIES = 1
_MAX_UNAVAILABLE_TOOL_RETRIES = 1

# Groq/OpenAI reject tool calls not present in request.tools before returning them.
_UNAVAILABLE_TOOL_RE = re.compile(
    r"attempted to call tool ['\"]([^'\"]+)['\"]",
    re.IGNORECASE,
)


def _validate_tool_args(
    tool_name: str, arguments: dict[str, Any]
) -> list[str]:
    """
    Return a list of argument names that are required but missing or empty.
    Empty string, None, and missing keys all count as missing.
    """
    tool_lower = tool_name.lower()
    for pattern, required in _REQUIRED_ARGS.items():
        if pattern in tool_lower:
            return [
                field
                for field in required
                if not arguments.get(field)  # catches None, "", 0, []
            ]
    return []


def _missing_args_message(
    tool_name: str,
    missing: list[str],
    arguments: dict[str, Any] | None = None,
    *,
    retries_exhausted: bool = False,
) -> str:
    """Build the corrective injection message sent back to the LLM."""
    tool_lower = tool_name.lower()
    missing_set = set(missing)

    if (
        "create_or_update_file" in tool_lower
        and missing_set & {"content", "message"}
    ):
        path = (arguments or {}).get("path") or "the file"
        return _github_create_or_update_file_repair(missing, path, retries_exhausted)

    missing_lines = "\n".join(f"- {field}" for field in missing)
    retry_note = ""
    if retries_exhausted:
        retry_note = (
            "\n\nYou already attempted to fix this call and failed again. "
            "Do NOT call this tool again. Ask the user for the missing information."
        )

    return (
        "Your previous tool call was rejected because it did not satisfy the tool schema.\n\n"
        f"Tool: {tool_name}\n\n"
        "Missing or empty required arguments:\n"
        f"{missing_lines}\n\n"
        "The tool schema requires ALL mandatory arguments to be present and non-empty.\n\n"
        "You MUST follow these rules:\n\n"
        "1. If you know the values for ALL required arguments, generate a new tool call "
        "containing every required argument.\n"
        "2. If you do NOT know one or more required arguments, DO NOT call the tool again.\n"
        "3. Instead, respond with a natural language question asking the user to provide "
        "the missing information.\n"
        "4. Do NOT guess, invent, or leave required arguments empty.\n"
        "5. Do NOT switch to another tool unless the user explicitly requested it.\n"
        "6. Do NOT retry the same invalid tool call.\n"
        "7. Your response must be either:\n"
        "   - a valid tool call, OR\n"
        "   - a question to the user requesting the missing information.\n\n"
        "Examples:\n\n"
        "BAD:\n"
        '<function=github_create_or_update_file>\n'
        '{\n'
        '  "owner":"Kishorp28",\n'
        '  "repo":"chatbot",\n'
        '  "path":"README.md"\n'
        '}\n'
        "</function>\n\n"
        "BAD:\n"
        '<function=github_create_or_update_file>\n'
        '{\n'
        '  "owner":"Kishorp28",\n'
        '  "repo":"chatbot",\n'
        '  "path":"README.md",\n'
        '  "content":"",\n'
        '  "message":""\n'
        '}\n'
        "</function>\n\n"
        "GOOD:\n"
        "What content would you like me to put in README.md, and what commit message "
        "should I use?\n\n"
        "GOOD:\n"
        '<function=github_create_or_update_file>\n'
        '{\n'
        '  "owner":"Kishorp28",\n'
        '  "repo":"chatbot",\n'
        '  "path":"README.md",\n'
        '  "branch":"main",\n'
        '  "content":"# Chatbot\\nThis repository contains...",\n'
        '  "message":"Add README file"\n'
        '}\n'
        "</function>"
        f"{retry_note}"
    )


def _github_create_or_update_file_repair(
    missing: list[str],
    path: str,
    retries_exhausted: bool,
) -> str:
    """Targeted repair prompt for github_create_or_update_file validation failures."""
    missing_lines = "\n".join(f"- {field}" for field in missing)
    retry_note = ""
    if retries_exhausted:
        retry_note = (
            "\n\nYou already attempted to fix this call and failed again. "
            "Do NOT call github_create_or_update_file again. "
            f'Ask the user: "What content should I place in {path}, and what commit message '
            'would you like me to use?"'
        )

    return (
        "Your previous call to github_create_or_update_file was rejected.\n\n"
        "Missing required arguments:\n"
        f"{missing_lines}\n\n"
        "You are NOT allowed to call github_create_or_update_file again unless every "
        "missing argument is provided and non-empty.\n\n"
        f'If you do not know the content of {path} or the commit message, ask the user:\n\n'
        f'"What content should I place in {path}, and what commit message would you like '
        f'me to use?"\n\n'
        "Do NOT:\n"
        "- call filesystem tools,\n"
        "- call GitHub tools with partial arguments,\n"
        "- invent file content,\n"
        "- emit empty strings."
        f"{retry_note}"
    )


def _allowed_tool_names(tools: list[Any]) -> set[str]:
    """Lowercase names of tools passed to the LLM for this request."""
    return {t.name.lower() for t in tools}


def _parse_unavailable_tool_error(exc: Exception) -> str | None:
    """
    Return the hallucinated tool name when the provider rejects a tool
    call that was not in request.tools (Groq 400 tool_use_failed).
    """
    msg = str(exc)
    msg_lower = msg.lower()
    if "not in request.tools" not in msg_lower and "tool_use_failed" not in msg_lower:
        return None
    match = _UNAVAILABLE_TOOL_RE.search(msg)
    return match.group(1) if match else "unknown"


def _unavailable_tool_rejected(
    tool_name: str,
    allowed: set[str],
    *,
    retries_exhausted: bool,
) -> str:
    """Repair prompt when the model calls a tool outside the active set."""
    base = unavailable_tool_message(tool_name, sorted(allowed))
    if retries_exhausted:
        return (
            f"{base}\n\n"
            "You already attempted to call an unavailable tool and failed again. "
            "Do NOT call any unavailable tool. Use one of the available tools listed "
            "above, or ask the user for clarification."
        )
    return base


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class GitHubAIAgent:
    """
    ReAct-style agent: LLM ↔ MCP tools loop until completion.

    The agent never calls GitHub/filesystem/git directly — every external
    action goes through MCP, preserving the protocol boundary.

    Conversation history is passed in externally so session persistence
    is handled at the HTTP layer (app.py).
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

    async def run(
        self,
        user_message: str,
        history: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """
        Process a user message and yield streaming events.

        Args:
            user_message: The new user input.
            history: Existing conversation turns (user/assistant/tool).
                     Mutated in-place so the caller gets the updated history.
        """
        if history is None:
            history = []

        try:
            self.llm.call_count = 0
            # Check if there is an existing serialized graph in history
            graph = None
            graph_msg_idx = -1
            for idx, m in enumerate(history):
                if m.get("role") == "system" and str(m.get("content")).startswith("TASK_GRAPH_STATE:"):
                    try:
                        graph = TaskGraph.from_dict(json.loads(m["content"][17:]))
                        graph_msg_idx = idx
                        break
                    except Exception:
                        pass

            # If no graph exists, run the Planner to build it
            if not graph:
                yield AgentEvent("status", {"message": "Analyzing request & generating execution plan..."})
                
                # Inherit state variables from the last recorded task graph in history
                inherited_state = {}
                for m in reversed(history):
                    if m.get("role") == "system" and str(m.get("content")).startswith("TASK_GRAPH_STATE:"):
                        try:
                            g_dict = json.loads(m["content"][17:])
                            inherited_state = g_dict.get("state_variables", {})
                            break
                        except Exception:
                            pass
                
                planner = Planner(self.llm)
                graph = await planner.generate_graph(user_message, self.mcp.tools, state_variables=inherited_state)
                # Keep inherited variables if not overwritten
                if inherited_state:
                    for k, v in inherited_state.items():
                        if k not in graph.state_variables:
                            graph.state_variables[k] = v
                history.append({"role": "system", "content": "TASK_GRAPH_STATE:" + json.dumps(graph.to_dict())})
                graph_msg_idx = len(history) - 1

            # Main task execution loop
            failed_calls = set()
            
            while not graph.is_complete():
                task = graph.get_next_task()
                if not task:
                    # Graph has failed or has no runnable tasks (e.g. max attempts exceeded)
                    break

                task.attempts += 1
                yield AgentEvent("status", {"message": f"Running step: {task.description}"})
                logger.info("Executing task %s (attempt %d/%d): %s", task.name, task.attempts, task.max_attempts, task.description)

                # Resolve placeholders in arguments from state variables
                resolved_args = {}
                for k, v in task.arguments.items():
                    if isinstance(v, str):
                        try:
                            resolved_args[k] = v.format(**graph.state_variables)
                        except KeyError:
                            resolved_args[k] = v
                    else:
                        resolved_args[k] = v

                # ── Deterministic Mode Execution ──
                if task.tool_name and task.tool_name.lower() in [t.name.lower() for t in self.mcp.tools]:
                    tool_name = task.tool_name
                    yield AgentEvent("tool_start", {"name": tool_name, "arguments": resolved_args})
                    try:
                        result = await self.mcp.call_tool(tool_name, resolved_args)
                        result_str = _serialize_tool_result(result)
                        yield AgentEvent("tool_end", {"name": tool_name, "result": result_str[:2000]})
                        
                        graph.mark_complete(task.name)
                        # Compile results as a compact summary message in history
                        history.append({
                            "role": "system",
                            "content": f"Task '{task.name}' completed: {result_str}"
                        })
                        # Save updated task graph back to history state
                        if graph_msg_idx != -1:
                            history[graph_msg_idx] = {"role": "system", "content": "TASK_GRAPH_STATE:" + json.dumps(graph.to_dict())}
                        
                        # Update graph state variables with successful args/results
                        if "repo" in resolved_args:
                            graph.state_variables["repo"] = resolved_args["repo"]
                        if "owner" in resolved_args:
                            graph.state_variables["owner"] = resolved_args["owner"]
                        if "branch" in resolved_args:
                            graph.state_variables["branch"] = resolved_args["branch"]
                        
                        # Smart post-processing: after listing a directory, find the
                        # actual readme filename and update downstream task arguments.
                        if task.name == "fetch_repo_structure" and resolved_args.get("path", None) in ("", None):
                            try:
                                dir_entries = json.loads(result_str) if isinstance(result_str, str) else result_str
                                if isinstance(dir_entries, list):
                                    readme_name = next(
                                        (e["name"] for e in dir_entries
                                         if isinstance(e, dict) and e.get("name", "").lower().startswith("readme")),
                                        None
                                    )
                                    if readme_name and "fetch_readme" in graph.nodes:
                                        old_path = graph.nodes["fetch_readme"].arguments.get("path", "")
                                        if old_path.lower() != readme_name.lower():
                                            logger.info(
                                                "Auto-correcting fetch_readme path: '%s' → '%s'",
                                                old_path, readme_name
                                            )
                                            graph.nodes["fetch_readme"].arguments["path"] = readme_name
                                            if graph_msg_idx != -1:
                                                history[graph_msg_idx] = {"role": "system", "content": "TASK_GRAPH_STATE:" + json.dumps(graph.to_dict())}
                            except Exception as parse_exc:
                                logger.debug("Could not parse directory listing to fix readme path: %s", parse_exc)
                        
                        continue
                    except Exception as exc:
                        logger.exception("Deterministic task tool execution failed")
                        result_str = str(exc)
                        yield AgentEvent("tool_error", {"name": tool_name, "error": result_str})
                        
                        logger.warning("Deterministic task %s failed: %s. Initiating re-planning...", task.name, result_str)
                        yield AgentEvent("status", {"message": f"Step '{task.name}' failed. Re-planning..."})
                        
                        planner = Planner(self.llm)
                        replan_graph = await planner.re_plan(user_message, graph, task.name, result_str, self.mcp.tools, history)
                        if replan_graph:
                            graph = replan_graph
                            if graph_msg_idx != -1:
                                history[graph_msg_idx] = {"role": "system", "content": "TASK_GRAPH_STATE:" + json.dumps(graph.to_dict())}
                        else:
                            graph.mark_failed(task.name, result_str)
                            if graph_msg_idx != -1:
                                history[graph_msg_idx] = {"role": "system", "content": "TASK_GRAPH_STATE:" + json.dumps(graph.to_dict())}
                        continue

                # ── Reasoning Mode Execution (localized ReAct loop) ──
                # Filter namespaced tools for this step
                active_tools = [t for t in self.mcp.tools if task.tool_namespace == "all" or t.server == task.tool_namespace]
                if task.tool_namespace == "all":
                    active_tools = _filter_tools_by_context(active_tools, user_message, history)
                allowed_tools = _allowed_tool_names(active_tools)
                system_content = build_system_prompt(active_tools)

                # Localized task history
                task_context = f"\n\nActive context variables:\n{json.dumps(graph.state_variables, indent=2)}" if graph.state_variables else ""
                
                # Gather completed tasks from history
                completed_tasks = []
                for m in history:
                    if m.get("role") == "system" and str(m.get("content")).startswith("Task '"):
                        completed_tasks.append(m["content"])
                
                completed_context = ""
                if completed_tasks:
                    completed_context = "\n\nResults of completed tasks in this session:\n" + "\n".join(completed_tasks)

                public_history = [m for m in history if m.get("role") != "system"]
                
                if task.tool_namespace == "all":
                    ns_warning = "You can call any active tools to satisfy the task."
                else:
                    ns_warning = f"You MUST only call tools belonging to the namespace '{task.tool_namespace}'."

                task_messages = [
                    {
                        "role": "system",
                        "content": (
                            f"{system_content}\n\n"
                            f"CURRENT TARGET SUB-TASK:\n{task.description}\n\n"
                            f"{ns_warning}\n"
                            "Do NOT attempt to solve future tasks. Focus purely on completing the target sub-task."
                            f"{completed_context}"
                            f"{task_context}"
                        )
                    },
                    *public_history,
                ]

                # Run a localized ReAct loop for this task (capped at 3 iterations)
                task_success = False
                task_error = None
                task_summary = ""
                
                for iteration in range(3):
                    # Check LLM call budget
                    if self.llm.call_count >= 10:
                        task_error = "Maximum LLM call budget (10) exceeded"
                        break
                    
                    try:
                        content, tool_calls, assistant_msg = await self.llm.chat(task_messages, active_tools)
                    except Exception as exc:
                        task_error = f"LLM Chat failed: {exc}"
                        break

                    if assistant_msg:
                        task_messages.append(assistant_msg)

                    if not tool_calls:
                        # LLM decided it is done with this task node
                        task_success = True
                        task_summary = content or "Task completed successfully."
                        break

                    # Execute tool calls
                    for tc in tool_calls:
                        tool_name = tc["name"]
                        tool_args = tc["arguments"]
                        tool_id = tc.get("id", tool_name)

                        # Reject tools not in namespace
                        if tool_name.lower() not in allowed_tools:
                            err = f"Tool '{tool_name}' is not in active task namespace '{task.tool_namespace}'."
                            task_messages.append({"role": "tool", "tool_call_id": tool_id, "content": err})
                            continue

                        # Reject repeated failures
                        cache_key = (tool_name, json.dumps(tool_args, sort_keys=True))
                        if cache_key in failed_calls:
                            task_error = f"Agent attempted a previously failed tool call: {tool_name}"
                            break

                        yield AgentEvent("tool_start", {"name": tool_name, "arguments": tool_args})

                        try:
                            # call_tool handles auto-injection, validation, caching, and recovery analysis!
                            result = await self.mcp.call_tool(tool_name, tool_args)
                            result_str = _serialize_tool_result(result)
                            yield AgentEvent("tool_end", {"name": tool_name, "result": result_str[:2000]})
                            
                            # Update graph state variables with successful args
                            if "repo" in tool_args:
                                graph.state_variables["repo"] = tool_args["repo"]
                            if "owner" in tool_args:
                                graph.state_variables["owner"] = tool_args["owner"]
                            if "branch" in tool_args:
                                graph.state_variables["branch"] = tool_args["branch"]
                                
                        except Exception as exc:
                            logger.exception("Task tool execution failed")
                            result_str = str(exc)
                            failed_calls.add(cache_key)
                            yield AgentEvent("tool_error", {"name": tool_name, "error": result_str})

                        task_messages.append({"role": "tool", "tool_call_id": tool_id, "content": result_str})

                    if task_error:
                        break

                if task_success:
                    graph.mark_complete(task.name)
                    # Compile results as a compact summary message in history
                    history.append({
                        "role": "system",
                        "content": f"Task '{task.name}' completed: {task_summary}"
                    })
                else:
                    err_msg = task_error or "Task failed to complete in maximum iterations."
                    logger.warning("Task %s failed: %s. Initiating re-planning...", task.name, err_msg)
                    yield AgentEvent("status", {"message": f"Step '{task.name}' failed. Re-planning..."})
                    
                    planner = Planner(self.llm)
                    replan_graph = await planner.re_plan(user_message, graph, task.name, err_msg, self.mcp.tools, history)
                    if replan_graph:
                        graph = replan_graph
                        if graph_msg_idx != -1:
                            history[graph_msg_idx] = {"role": "system", "content": "TASK_GRAPH_STATE:" + json.dumps(graph.to_dict())}
                        continue
                    else:
                        graph.mark_failed(task.name, err_msg)
                        logger.error("Task %s failed: %s", task.name, err_msg)

                # Save updated task graph back to history state
                if graph_msg_idx != -1:
                    history[graph_msg_idx] = {"role": "system", "content": "TASK_GRAPH_STATE:" + json.dumps(graph.to_dict())}

            # Final Synthesis phase
            if graph.is_complete():
                yield AgentEvent("status", {"message": "Generating final response..."})
                
                # Gather actual user/assistant dialog history
                dialog_history = [
                    m for m in history
                    if m.get("role") in ("user", "assistant")
                ]
                
                # Gather completed task results
                task_results = []
                for m in history:
                    if m.get("role") == "system" and str(m.get("content")).startswith("Task '"):
                        task_results.append(str(m.get("content")))
                
                task_results_context = ""
                if task_results:
                    task_results_context = "\n\nRetrieved task results and repository files:\n" + "\n".join(task_results)
                
                # Final LLM run to synthesize and explain what was done
                synthesis_messages = [
                    {
                        "role": "system",
                        "content": (
                            "You are GitHub AI Engineer. All tasks have completed successfully.\n"
                            "Based on the retrieved task results and repository files, write a detailed, direct, "
                            "and comprehensive response that fully answers the user's latest request. "
                            "Do not describe the execution steps or graph tasks; answer the user's question "
                            "directly using the retrieved data."
                        )
                    },
                    *dialog_history,
                    {
                        "role": "user",
                        "content": (
                            f"Original user request: {user_message}\n\n"
                            f"Please provide the final answer to this request using the retrieved data below.{task_results_context}"
                        )
                    }
                ]
                if self.llm.call_count >= 10:
                    final_answer = "All tasks completed successfully. Synthesized final response skipped to stay within request budget."
                else:
                    content, _, _ = await self.llm.chat(synthesis_messages, tools=[])
                    final_answer = content or "All tasks successfully completed."
            else:
                # Compile details of task failures to explain to the user
                failed_steps = [f"- {n.name}: {n.error}" for n in graph.nodes.values() if n.status == "failed"]
                failed_steps_str = "\n".join(failed_steps)
                final_answer = (
                    "I was unable to complete the request because some task steps failed:\n\n"
                    f"{failed_steps_str}\n\n"
                    "Please verify your request or repository settings and try again."
                )

            # Stream final response to the frontend
            history.append({"role": "assistant", "content": final_answer})
            yield AgentEvent("message_start", {})
            async for chunk in self.llm.stream_text(final_answer):
                yield AgentEvent("message_delta", {"content": chunk})
            yield AgentEvent("message_end", {})

        except Exception as exc:
            logger.exception("Agent run failed")
            yield AgentEvent("error", {"message": f"Agent error: {exc}"})


# ---------------------------------------------------------------------------
# Tool filtering
# ---------------------------------------------------------------------------

def _filter_tools_by_context(
    all_tools: list[Any],
    user_message: str,
    history: list[dict[str, Any]],
) -> list[Any]:
    """
    Decide which MCP servers are relevant for this message.

    Rules:
    1. Greetings / conversational messages  → [] (LLM answers from training)
    2. General questions with no tool need  → [] (same)
    3. Technical messages → only the servers whose keywords appear in the query.
    """
    query = user_message.lower().strip()

    # ── 1. Conversational short-circuit ──────────────────────────────────────
    _GREET = {
        "hi", "hii", "hiii", "hello", "hey", "howdy", "yo", "sup",
        "good morning", "good evening", "good night", "good afternoon",
        "how are you", "how r u", "what's up", "whats up",
        "who are you", "what are you", "what can you do",
        "what is your name", "tell me about yourself",
        "thanks", "thank you", "thx", "ty", "ok", "okay", "cool", "nice",
        "bye", "goodbye", "see you",
    }
    is_greeting = query in _GREET or any(
        query == g or query.startswith(g + " ") or query.startswith(g + ",")
        for g in _GREET
    )
    if is_greeting:
        return []

    # ── 2. Per-server keyword sets ────────────────────────────────────────────
    _GITHUB_KW = {
        "github", "issue", "issues", "pr", "prs", "gist", "gists",
        "release", "releases", "workflow", "workflows", "actions", "organization", "org",
        "fork", "forks", "star", "stars", "watch", "milestones", "milestone", "label", "labels",
        "repository", "repo", "repos", "pullrequest", "pullrequests"
    }
    _GIT_KW = {
        "git", "commit", "commits", "diff", "log", "status",
        "branch", "branches", "push", "pull", "fetch",
        "merge", "rebase", "stash", "tag", "blame", "cherry",
        "history", "add", "checkout", "init", "reset", "remote"
    }
    _FS_KW = {
        "file", "files", "read", "write", "edit", "code", "function", "class", "method",
        "module", "package", "directory", "folder", "path", "source", "create",
        "import", "implement", "security", "vulnerability", "vulnerabilit", "bug", "bugs",
        "explain", "architecture", "endpoint", "api", "route", "schema", "config", "env",
        "test", "tests", "lint", "format", "refactor", "dependency", "dependencies"
    }

    # Tokenize input query into words to match against keywords
    words = set(re.findall(r"\b\w+\b", query))

    needs_github = bool(words & _GITHUB_KW) or "pull request" in query or "pull requests" in query
    needs_git = bool(words & _GIT_KW)
    needs_files = bool(words & _FS_KW)

    # ── 3. No technical intent → default to all tools to prevent blocking unexpected requests
    if not needs_github and not needs_git and not needs_files:
        needs_github = True
        needs_git = True
        needs_files = True

    # ── 4. Build filtered list ────────────────────────────────────────────────
    filtered = []
    for t in all_tools:
        server = t.server or ""
        if server == "github"     and not needs_github:
            continue
        if server == "git"        and not needs_git:
            continue
        if server == "filesystem" and not needs_files:
            continue
        filtered.append(t)

    return filtered


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _classify_llm_error(exc: Exception) -> str:
    """Return a user-facing error message based on exception type/message."""
    msg = str(exc).lower()
    if "rate limit" in msg or "ratelimit" in msg or "429" in msg:
        return (
            "The LLM provider rate limit was reached. "
            "Wait a moment and try again."
        )
    if "context" in msg and ("length" in msg or "window" in msg or "token" in msg):
        return (
            "The conversation has exceeded the model's context window. "
            "Start a new chat to continue."
        )
    if "authentication" in msg or "api key" in msg or "unauthorized" in msg or "401" in msg:
        return "LLM authentication failed. Check your API key in .env."
    if "timeout" in msg or "timed out" in msg:
        return "The LLM request timed out. Please try again."
    if "not in request.tools" in msg or "tool_use_failed" in msg:
        return (
            "The model tried to call a tool that is not active for this request. "
            "Try rephrasing your question or start a new chat."
        )
    return f"LLM error: {exc}"


def _serialize_tool_result(result: Any) -> str:
    """Normalize any tool result into a JSON string the LLM can consume."""
    if result is None:
        return "null"
    if isinstance(result, str):
        return result
    try:
        return json.dumps(result, indent=2, default=str)
    except (TypeError, ValueError):
        return str(result)
