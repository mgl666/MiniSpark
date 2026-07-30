"""Tool registry: aggregates built-in / Skill / MCP sources, exposes a unified interface to the core loop."""

from __future__ import annotations

import logging
from typing import Any

from minispark.tools.base import FunctionTool

logger = logging.getLogger(__name__)

_TRUNCATED_MARK = "\n... [Result too long, truncated]"


class ToolRegistry:
    """Tool registration and execution hub. Built-in tools, Skills, and MCP remote tools converge here."""

    def __init__(self, result_char_limit: int = 8000) -> None:
        self._tools: dict[str, FunctionTool] = {}
        self._char_limit = result_char_limit

    def register(self, tool: FunctionTool) -> None:
        if tool.name in self._tools:
            logger.warning("Tool %s duplicate registration, latter overwrites former", tool.name)
        self._tools[tool.name] = tool

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    @property
    def tools(self) -> list[FunctionTool]:
        """All registered tools (read-only)."""
        return list(self._tools.values())

    def schemas(self) -> list[dict[str, Any]]:
        """All tools' OpenAI tools format schema list."""
        return [t.schema for t in self._tools.values()]

    def _truncate(self, result: str) -> str:
        if len(result) > self._char_limit:
            return result[: self._char_limit] + _TRUNCATED_MARK
        return result

    async def execute(self, name: str, arguments: dict[str, Any]) -> str:
        """Execute a single tool call.

        All failures (tool not found / parameter error / execution exception) are converted to error text,
        backfilled to the model for self-adjustment instead of crashing the Agent.
        """
        tool = self._tools.get(name)
        if tool is None:
            return f"Error: Tool {name!r} does not exist. Available tools: {', '.join(sorted(self._tools))}"
        try:
            result = await tool.run(arguments)
        except ValueError as exc:  # Parameter validation failure
            logger.warning("Tool %s parameter error: %s", name, exc)
            return f"Error: {exc}"
        except Exception as exc:  # noqa: BLE001 - catch-all, exception must be backfilled not thrown
            logger.exception("Tool %s execution exception", name)
            return f"Error: Tool execution exception: {type(exc).__name__}: {exc}"
        return self._truncate(result)