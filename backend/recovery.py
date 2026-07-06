from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class RecoveryStrategy:
    """Represents a recovery action determined by the Recovery Engine."""

    def __init__(self, action: str, description: str, args_override: dict[str, Any] | None = None) -> None:
        self.action = action  # 'retry_with_args', 'fail_task', 'ask_user', 'no_action'
        self.description = description
        self.args_override = args_override or {}


class RecoveryEngine:
    """Deterministic failure analysis and recovery recommendation engine."""

    def __init__(self) -> None:
        pass

    async def analyze_failure(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        error_message: str,
    ) -> RecoveryStrategy:
        err_lower = error_message.lower()
        
        # 1. Handle GitHub 404 Not Found
        if "not found" in err_lower or "404" in err_lower:
            logger.info("RecoveryEngine detected 404 error on %s", tool_name)
            if tool_name == "github_get_file_contents":
                desc = (
                    "The requested GitHub file or branch does not exist.\n\n"
                    "Next Steps:\n"
                    "1. Call github_get_repository to verify the repository exists and determine its default_branch.\n"
                    "2. Call github_list_directory to inspect the repository root files.\n"
                    "3. Retry reading the correct file using the default branch."
                )
                return RecoveryStrategy("fail_task", desc)
        
        # 2. Handle Authentication / Permission Failures (401/403)
        if "unauthorized" in err_lower or "401" in err_lower or "403" in err_lower or "bad credentials" in err_lower:
            logger.info("RecoveryEngine detected Authentication/Permission error on %s", tool_name)
            desc = (
                "GitHub authentication failed. This is likely due to an invalid or expired GITHUB_PERSONAL_ACCESS_TOKEN.\n\n"
                "Please verify that your token is set correctly in your .env file and has active 'repo' permissions."
            )
            return RecoveryStrategy("fail_task", desc)

        # 3. Handle Local Git Path Traversal / Repo mismatch
        if "not a git repository" in err_lower:
            logger.info("RecoveryEngine detected directory mismatch for Git tool %s", tool_name)
            desc = (
                "The current working directory is not a valid Git repository checkout.\n\n"
                "Next Steps:\n"
                "1. Verify that your settings.git_repository_path is pointing to the correct repository root.\n"
                "2. Verify git is initialized by calling git_git_status."
            )
            return RecoveryStrategy("fail_task", desc)

        # 4. Default fallback: Let the task fail and explain the exception
        return RecoveryStrategy("no_action", f"Tool execution failed: {error_message}")
