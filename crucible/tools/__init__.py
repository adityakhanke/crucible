"""Tool Router — ~150 LOC declarative tool execution layer.

Loads the tool manifest from YAML. Read-only tools execute immediately.
Tools with requires_approval=true pause for human review.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Optional

from crucible.config import tools as load_tools_config

logger = logging.getLogger(__name__)


@dataclass
class ToolSpec:
    name: str
    tool_type: str
    endpoint: Optional[str]
    permissions: list[str]
    rate_limit: Optional[int]
    requires_approval: bool
    extra: dict


class ToolRouter:
    """Routes tool invocations through the declarative manifest.

    Usage:
        router = ToolRouter()
        router.register_handler("arxiv_search", arxiv_search_fn)
        result = router.invoke("arxiv_search", {"query": "transformer scaling laws"})
    """

    def __init__(self):
        cfg = load_tools_config()
        self._specs: dict[str, ToolSpec] = {}
        self._handlers: dict[str, Callable] = {}
        self._pending_approvals: list[dict] = []

        for name, tcfg in cfg.get("tools", {}).items():
            self._specs[name] = ToolSpec(
                name=name,
                tool_type=tcfg.get("type", "unknown"),
                endpoint=tcfg.get("endpoint"),
                permissions=tcfg.get("permissions", []),
                rate_limit=tcfg.get("rate_limit"),
                requires_approval=tcfg.get("requires_approval", False),
                extra={k: v for k, v in tcfg.items() if k not in (
                    "type", "endpoint", "permissions", "rate_limit", "requires_approval"
                )},
            )

        logger.info(f"ToolRouter loaded {len(self._specs)} tool specs.")

    def register_handler(self, tool_name: str, handler: Callable):
        """Register an execution handler for a tool."""
        if tool_name not in self._specs:
            raise KeyError(f"Unknown tool: {tool_name}")
        self._handlers[tool_name] = handler

    def invoke(self, tool_name: str, params: dict[str, Any] = None) -> dict:
        """Invoke a tool. Returns result or queues for approval.

        Returns:
            {"status": "completed", "result": ...}
            {"status": "pending_approval", "tool": ..., "params": ...}
            {"status": "error", "message": ...}
        """
        params = params or {}

        if tool_name not in self._specs:
            return {"status": "error", "message": f"Unknown tool: {tool_name}"}

        spec = self._specs[tool_name]

        if spec.requires_approval:
            entry = {"tool": tool_name, "params": params, "spec": spec}
            self._pending_approvals.append(entry)
            logger.warning(f"Tool '{tool_name}' requires approval. Queued.")
            return {"status": "pending_approval", "tool": tool_name, "params": params}

        if tool_name not in self._handlers:
            return {"status": "error", "message": f"No handler registered for: {tool_name}"}

        try:
            result = self._handlers[tool_name](**params)
            return {"status": "completed", "result": result}
        except Exception as e:
            logger.error(f"Tool '{tool_name}' failed: {e}")
            return {"status": "error", "message": str(e)}

    def get_pending_approvals(self) -> list[dict]:
        """Get all pending approval requests."""
        return list(self._pending_approvals)

    def approve(self, index: int) -> dict:
        """Approve and execute a pending tool call."""
        if index >= len(self._pending_approvals):
            return {"status": "error", "message": "Invalid approval index"}

        entry = self._pending_approvals.pop(index)
        tool_name = entry["tool"]

        if tool_name not in self._handlers:
            return {"status": "error", "message": f"No handler for: {tool_name}"}

        try:
            result = self._handlers[tool_name](**entry["params"])
            return {"status": "completed", "result": result}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def reject(self, index: int):
        """Reject a pending tool call."""
        if index < len(self._pending_approvals):
            self._pending_approvals.pop(index)

    @property
    def available_tools(self) -> list[str]:
        return list(self._specs.keys())

    def get_spec(self, tool_name: str) -> Optional[ToolSpec]:
        return self._specs.get(tool_name)
