from __future__ import annotations

import json
import logging
import re
from typing import Any

from graph import TaskGraph, TaskNode
from services.llm import LLMService

logger = logging.getLogger(__name__)


PLANNING_SYSTEM_PROMPT = """\
You are an expert Software Agent Planner. Your task is to analyze the user's request and build a structured Task Graph (DAG) to accomplish it.

You must output a JSON object ONLY, containing:
1. "tasks": a list of task objects.
2. "state_variables": a dictionary of initial context parameters (e.g., owner, repo, branch, files).

Each task in "tasks" must have:
- "name": (str) unique identifier.
- "description": (str) what the task does.
- "tool_namespace": (str) one of "git", "filesystem", "github", "all".
- "arguments": (dict) the arguments that will be passed to tools executing this step.
- "dependencies": (list of str) names of other tasks that must complete successfully before this task can start.
- "tool_name": (str, optional) the exact name of the tool to invoke if this step can be executed deterministically (e.g., "filesystem_read_text_file", "github_get_file_contents", "git_git_status", "filesystem_write_file"). Omitting this field means the agent will use reasoning to satisfy the task.

Core tool capabilities:
- git: status, checkout, branch, commit, add, log, diff, pull, push, fetch.
- github: create_or_update_file, get_file_contents, create_pull_request, get_repository, list_directory, search_code, list_commits, create_issue, merge_pull_request.
- filesystem: read_file, write_file, edit_file, list_directory, search_files.

RULES:
1. Keep the graph minimal and focused. Do not add redundant search/list tasks.
2. The repository is already checked out locally on the filesystem. Do NOT create tasks to check out, clone, status check, or pull the repository unless the user specifically asks you to sync or pull changes. Start directly with filesystem or github tools.
3. Respect dependencies: writing a file depends on checking its existence or reading it.
4. Be precise with argument keys (e.g. "owner", "repo", "path", "branch", "content", "message").
5. Output valid JSON only, without any surrounding markdown blocks or extra conversational text.
"""


# Module-level cache to persist plans across requests/re-instantiations
_plan_cache: dict[str, dict[str, Any]] = {}


class Planner:
    """Uses the LLM to parse requests into a structured TaskGraph (DAG)."""

    def __init__(self, llm: LLMService) -> None:
        self.llm = llm

    async def generate_graph(
        self,
        user_prompt: str,
        available_tools: list[Any],
        state_variables: dict[str, Any] | None = None
    ) -> TaskGraph:
        import hashlib
        # Include state_variables in the hash to differentiate context-specific plans
        prompt_str = f"{user_prompt}:{json.dumps(state_variables or {}, sort_keys=True)}"
        prompt_hash = hashlib.sha256(prompt_str.encode("utf-8")).hexdigest()
        
        if prompt_hash in _plan_cache:
            logger.info("PLANNER CACHE HIT: Reusing cached task graph for prompt hash %s", prompt_hash)
            return TaskGraph.from_dict(_plan_cache[prompt_hash])

        github_url_match = re.search(r"github\.com/([\w\-\.]+)/([\w\-\.]+)", user_prompt)
        if github_url_match:
            owner = github_url_match.group(1)
            repo = github_url_match.group(2).replace(".git", "").strip("/")
            logger.info("Heuristic match: GitHub repository URL detected (%s/%s). Generating targeted retrieval plan.", owner, repo)
            
            graph = TaskGraph()
            graph.state_variables = {"owner": owner, "repo": repo}
            
            # Step 1: List root directory (no branch = uses repo default branch)
            # This both confirms the repo exists AND reveals the exact filenames/casing
            node_list = TaskNode(
                name="fetch_repo_structure",
                description=f"Retrieve the root directory listing of '{owner}/{repo}' to find all files and their exact names.",
                tool_namespace="github",
                tool_name="github_get_file_contents",
                arguments={"owner": owner, "repo": repo, "path": ""},
                dependencies=[]
            )
            # Step 2: Try readme.md (lowercase first — many repos use lowercase)
            node_readme = TaskNode(
                name="fetch_readme",
                description=(
                    f"Retrieve the README/readme file from '{owner}/{repo}'. "
                    "Try 'readme.md' first (lowercase). If that fails, the re-planner will try 'README.md'."
                ),
                tool_namespace="github",
                tool_name="github_get_file_contents",
                arguments={"owner": owner, "repo": repo, "path": "readme.md"},
                dependencies=["fetch_repo_structure"]
            )
            graph.add_node(node_list)
            graph.add_node(node_readme)
            
            _plan_cache[prompt_hash] = graph.to_dict()
            return graph

        # Format available tools list for the planner
        tools_summary = "\n".join(
            f"- {t.name} (namespace: {t.server or 'unknown'}) - {t.description[:80]}"
            for t in available_tools
        )

        context_info = ""
        if state_variables:
            context_info = f"\nInherited context variables from previous turns:\n{json.dumps(state_variables, indent=2)}\nUse these variables if they satisfy references in the user request (e.g. 'this repo', 'these files').\n"

        messages = [
            {"role": "system", "content": PLANNING_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"User Request: {user_prompt}\n{context_info}\nAvailable tools:\n{tools_summary}",
            },
        ]

        logger.info("Generating task plan...")
        # Call LLM without tools (we want a plain text JSON response)
        content, _, _ = await self.llm.chat(messages, tools=[])
        
        if not content:
            logger.warning("Planner failed to return content. Building fallback graph.")
            return self._build_fallback_graph(user_prompt)

        try:
            # Extract JSON block if model wrapped it in markdown code blocks
            clean_content = content.strip()
            
            # Remove Python/Shell-style comments from JSON
            clean_content = re.sub(r"#.*", "", clean_content)
            
            # Replace Python capitalization booleans with JSON equivalents
            clean_content = re.sub(r"\bTrue\b", "true", clean_content)
            clean_content = re.sub(r"\bFalse\b", "false", clean_content)
            clean_content = re.sub(r"\bNone\b", "null", clean_content)
            
            json_match = re.search(r"({.*})", clean_content, re.DOTALL)
            if json_match:
                clean_content = json_match.group(1)

            data = json.loads(clean_content)
            
            graph = TaskGraph()
            graph.state_variables = data.get("state_variables", {})

            for t_data in data.get("tasks", []):
                # Ensure all required fields exist
                node = TaskNode(
                    name=t_data["name"],
                    description=t_data["description"],
                    tool_namespace=t_data.get("tool_namespace", "all"),
                    arguments=t_data.get("arguments", {}),
                    dependencies=t_data.get("dependencies", []),
                    tool_name=t_data.get("tool_name"),
                )
                graph.add_node(node)

            logger.info("Task plan successfully generated with %d tasks.", len(graph.nodes))
            _plan_cache[prompt_hash] = graph.to_dict()
            return graph

        except Exception as exc:
            logger.exception("Failed to parse task plan JSON. content: %s", content)
            return self._build_fallback_graph(user_prompt)

    def _build_fallback_graph(self, user_prompt: str) -> TaskGraph:
        """Create a default safe task graph when LLM planning fails."""
        logger.info("Building fallback single-step task graph.")
        graph = TaskGraph()
        
        # Single-step general task that acts like the old ReAct agent
        node = TaskNode(
            name="execute_request",
            description=f"Process request: {user_prompt}",
            tool_namespace="all",
            arguments={},
        )
        graph.add_node(node)
        return graph

    async def re_plan(
        self,
        user_prompt: str,
        current_graph: TaskGraph,
        failed_task_name: str,
        error_message: str,
        available_tools: list[Any],
        history: list[dict[str, Any]] | None = None
    ) -> TaskGraph | None:
        """
        Invoked when a task fails. Re-evaluates the DAG and inserts recovery steps.
        """
        logger.info("Re-planning task graph after failure of %s: %s", failed_task_name, error_message)
        
        # Clear any cached plan for this prompt to force fresh planning next time
        # (avoids reusing a plan that led to this failure)
        import hashlib
        prompt_hash = hashlib.sha256(user_prompt.encode("utf-8")).hexdigest()
        _plan_cache.pop(prompt_hash, None)
        
        completions_summary = ""
        if history:
            completions = []
            for m in history:
                if m.get("role") == "system" and "completed:" in str(m.get("content")):
                    completions.append(str(m["content"]))
            if completions:
                completions_summary = "Past task execution results:\n" + "\n".join(completions) + "\n\n"

        tools_summary = "\n".join(
            f"- {t.name} (namespace: {t.server or 'unknown'}) - {t.description[:80]}"
            for t in available_tools
        )
        
        replan_prompt = (
            f"Original User Request: {user_prompt}\n\n"
            f"{completions_summary}"
            f"Current Task Graph state:\n{json.dumps(current_graph.to_dict(), indent=2)}\n\n"
            f"Failed Task: {failed_task_name}\n"
            f"Error Encountered: {error_message}\n\n"
            "You MUST output an updated JSON object matching the planner schema. "
            "You can add new tasks, modify arguments of existing tasks, insert dependencies, "
            "or reset task statuses (e.g. change a failed/completed task status back to 'pending' to retry it after running new pre-requisite steps).\n"
            f"Available tools:\n{tools_summary}"
        )
        
        messages = [
            {"role": "system", "content": PLANNING_SYSTEM_PROMPT},
            {"role": "user", "content": replan_prompt}
        ]
        
        content, _, _ = await self.llm.chat(messages, tools=[])
        if not content:
            return None
            
        try:
            clean_content = content.strip()
            clean_content = re.sub(r"#.*", "", clean_content)
            clean_content = re.sub(r"\bTrue\b", "true", clean_content)
            clean_content = re.sub(r"\bFalse\b", "false", clean_content)
            clean_content = re.sub(r"\bNone\b", "null", clean_content)
            
            json_match = re.search(r"({.*})", clean_content, re.DOTALL)
            if json_match:
                clean_content = json_match.group(1)
                
            data = json.loads(clean_content)
            
            new_graph = TaskGraph()
            new_graph.state_variables = data.get("state_variables", current_graph.state_variables)
            
            for t_data in data.get("tasks", []):
                node = TaskNode(
                    name=t_data["name"],
                    description=t_data["description"],
                    tool_namespace=t_data.get("tool_namespace", "all"),
                    arguments=t_data.get("arguments", {}),
                    dependencies=t_data.get("dependencies", []),
                    tool_name=t_data.get("tool_name"),
                )
                if node.name in current_graph.nodes:
                    node.attempts = current_graph.nodes[node.name].attempts
                    node.status = t_data.get("status", current_graph.nodes[node.name].status)
                else:
                    node.status = t_data.get("status", "pending")
                    
                new_graph.add_node(node)
                
            logger.info("Successfully re-planned task graph. New graph has %d tasks.", len(new_graph.nodes))
            return new_graph
        except Exception:
            logger.exception("Failed to parse re-planned task graph JSON.")
            return None
