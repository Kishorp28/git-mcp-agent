from __future__ import annotations

import json
from typing import Any, Literal


class TaskNode:
    """Represents a single step in the TaskGraph."""

    def __init__(
        self,
        name: str,
        description: str,
        tool_namespace: Literal["git", "filesystem", "github", "all"],
        arguments: dict[str, Any],
        dependencies: list[str] | None = None,
        max_attempts: int = 2,
        tool_name: str | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.tool_namespace = tool_namespace
        self.arguments = arguments
        self.dependencies = dependencies or []
        self.status: Literal["pending", "running", "completed", "failed"] = "pending"
        self.attempts = 0
        self.max_attempts = max_attempts
        self.error: str | None = None
        self.tool_name = tool_name

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "tool_namespace": self.tool_namespace,
            "arguments": self.arguments,
            "dependencies": self.dependencies,
            "status": self.status,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "error": self.error,
            "tool_name": self.tool_name,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskNode:
        node = cls(
            name=data["name"],
            description=data["description"],
            tool_namespace=data["tool_namespace"],
            arguments=data["arguments"],
            dependencies=data["dependencies"],
            max_attempts=data.get("max_attempts", 2),
            tool_name=data.get("tool_name"),
        )
        node.status = data["status"]
        node.attempts = data["attempts"]
        node.error = data.get("error")
        return node


class TaskGraph:
    """Manages execution state, task ordering, and variable context."""

    def __init__(self) -> None:
        self.nodes: dict[str, TaskNode] = {}
        self.state_variables: dict[str, Any] = {}

    def add_node(self, node: TaskNode) -> None:
        self.nodes[node.name] = node

    def is_complete(self) -> bool:
        """Returns True if all nodes are successfully completed."""
        if not self.nodes:
            return False
        return all(node.status == "completed" for node in self.nodes.values())

    def get_next_task(self) -> TaskNode | None:
        """
        Return the next task that can be executed (status is pending or failed
        but with attempts remaining, and all dependencies are completed).
        """
        for node in self.nodes.values():
            if node.status in ("pending", "failed") and node.attempts < node.max_attempts:
                # Check dependencies
                deps_ok = True
                for dep_name in node.dependencies:
                    dep_node = self.nodes.get(dep_name)
                    if not dep_node or dep_node.status != "completed":
                        deps_ok = False
                        break
                if deps_ok:
                    return node
        return None

    def mark_complete(self, task_name: str) -> None:
        if task_name in self.nodes:
            self.nodes[task_name].status = "completed"

    def mark_failed(self, task_name: str, error: str) -> None:
        if task_name in self.nodes:
            node = self.nodes[task_name]
            node.status = "failed"
            node.error = error

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": {name: node.to_dict() for name, node in self.nodes.items()},
            "state_variables": self.state_variables,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskGraph:
        graph = cls()
        for name, node_data in data.get("nodes", {}).items():
            graph.nodes[name] = TaskNode.from_dict(node_data)
        graph.state_variables = data.get("state_variables", {})
        return graph
