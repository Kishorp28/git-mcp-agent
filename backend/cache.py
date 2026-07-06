from __future__ import annotations

import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class CacheManager:
    """
    Invalidation-aware cache.
    Caches tool execution results and invalidates query caches upon mutation side-effects.
    """

    def __init__(self) -> None:
        # Cache format: key -> {"ok": bool, "data": Any, "error": str, "timestamp": float}
        self._cache: dict[tuple[str, str], dict[str, Any]] = {}

    def _generate_key(self, tool_name: str, args: dict[str, Any]) -> tuple[str, str]:
        # Serialize arguments deterministically
        return (tool_name, json.dumps(args, sort_keys=True))

    def get(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any] | None:
        key = self._generate_key(tool_name, args)
        return self._cache.get(key)

    def set(self, tool_name: str, args: dict[str, Any], result: Any, ok: bool = True) -> None:
        # Only cache successful results — errors should never be cached because
        # replanning may retry the same tool with (partially) different arguments or
        # after a prerequisite step has resolved the root cause (e.g. wrong branch).
        if not ok:
            return
        key = self._generate_key(tool_name, args)
        entry = {
            "ok": True,
            "timestamp": time.time(),
            "data": result,
        }
        self._cache[key] = entry

    def invalidate_on_mutation(self, tool_name: str, args: dict[str, Any]) -> None:
        """
        Invalidate query caches that could become stale because of this mutating tool call.
        """
        # Mapping from mutating tool prefixes to query tool names to invalidate
        mutations = {
            "filesystem_write_file": [
                "filesystem_read_file",
                "filesystem_read_text_file",
                "filesystem_read_multiple_files",
                "filesystem_directory_tree",
                "filesystem_list_directory",
                "filesystem_list_directory_with_sizes",
                "filesystem_search_files",
            ],
            "filesystem_edit_file": [
                "filesystem_read_file",
                "filesystem_read_text_file",
                "filesystem_read_multiple_files",
                "filesystem_directory_tree",
                "filesystem_list_directory",
                "filesystem_list_directory_with_sizes",
            ],
            "github_create_or_update_file": [
                "github_get_file_contents",
                "github_list_pull_requests",
                "github_search_code",
                "github_list_commits",
            ],
            "github_push_files": [
                "github_get_file_contents",
                "github_list_pull_requests",
                "github_search_code",
                "github_list_commits",
            ],
            "git_git_commit": [
                "git_git_status",
                "git_git_log",
                "git_git_diff",
                "git_git_diff_unstaged",
                "git_git_diff_staged",
            ],
            "git_git_add": [
                "git_git_status",
                "git_git_diff",
                "git_git_diff_unstaged",
                "git_git_diff_staged",
            ],
            "git_git_checkout": [
                "git_git_status",
                "git_git_branch",
                "git_git_log",
                "git_git_diff",
            ],
        }

        # Check if the tool name matches or starts with any of the mutating actions
        matched_queries = []
        for mut_tool, queries in mutations.items():
            if tool_name == mut_tool or tool_name.startswith(mut_tool + "_"):
                matched_queries.extend(queries)

        if not matched_queries:
            return

        target_path = args.get("path") or args.get("repo_path")
        keys_to_remove = []

        for cache_key in self._cache.keys():
            cached_tool, cached_args_str = cache_key
            
            # If the cached tool is in the set of tools invalidated by this mutation
            if cached_tool in matched_queries:
                # If target path matches, or if we want to be safe and clear all of that tool's cache
                try:
                    cached_args = json.loads(cached_args_str)
                    cached_path = cached_args.get("path") or cached_args.get("repo_path")
                    # If target path is unspecified, clear all. Otherwise, clear only if target path is in cached path
                    if not target_path or not cached_path or target_path == cached_path:
                        keys_to_remove.append(cache_key)
                except Exception:
                    keys_to_remove.append(cache_key)

        if keys_to_remove:
            logger.info("Invalidating %d cached entries due to mutation by %s", len(keys_to_remove), tool_name)
            for k in keys_to_remove:
                self._cache.pop(k, None)
