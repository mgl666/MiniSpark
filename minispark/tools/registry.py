"""工具注册表：聚合内置 / Skill / MCP 三个来源，对核心循环暴露统一接口。"""

from __future__ import annotations

import logging
from typing import Any

from minispark.tools.base import FunctionTool

logger = logging.getLogger(__name__)

_TRUNCATED_MARK = "\n... [结果过长已截断]"


class ToolRegistry:
    """工具注册与执行中心。内置工具、Skill、MCP 远端工具在此汇合。"""

    def __init__(self, result_char_limit: int = 8000) -> None:
        self._tools: dict[str, FunctionTool] = {}
        self._char_limit = result_char_limit

    def register(self, tool: FunctionTool) -> None:
        if tool.name in self._tools:
            logger.warning("工具 %s 重复注册，后者覆盖前者", tool.name)
        self._tools[tool.name] = tool

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    @property
    def tools(self) -> list[FunctionTool]:
        """所有已注册工具（只读）。"""
        return list(self._tools.values())

    def schemas(self) -> list[dict[str, Any]]:
        """全部工具的 OpenAI tools 格式 schema 列表。"""
        return [t.schema for t in self._tools.values()]

    def _truncate(self, result: str) -> str:
        if len(result) > self._char_limit:
            return result[: self._char_limit] + _TRUNCATED_MARK
        return result

    async def execute(self, name: str, arguments: dict[str, Any]) -> str:
        """执行一次工具调用。

        所有失败（工具不存在 / 参数错误 / 执行异常）都转成错误文本返回，
        回填给模型让它自行调整，而不是让 Agent 崩溃。
        """
        tool = self._tools.get(name)
        if tool is None:
            return f"错误：工具 {name!r} 不存在。可用工具：{', '.join(sorted(self._tools))}"
        try:
            result = await tool.run(arguments)
        except ValueError as exc:  # 参数校验失败
            logger.warning("工具 %s 参数错误: %s", name, exc)
            return f"错误：{exc}"
        except Exception as exc:  # noqa: BLE001 - 兜底，异常必须回填而非抛出
            logger.exception("工具 %s 执行异常", name)
            return f"错误：工具执行异常: {type(exc).__name__}: {exc}"
        return self._truncate(result)