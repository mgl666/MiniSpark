"""Tool layer: Tool abstraction, registry, and three extension mechanisms (Function Call / Skill / MCP).

Built-in Function Call tools are in the function_call/ subdirectory (fs / shell / web / memory...),
To add a new tool, create a .py file in function_call/, write a function with type annotations and docstring,
then register it in ``build_default_registry`` in ``core/agent.py``.
"""

from minispark.tools.base import FunctionTool, tool
from minispark.tools.function_call.fs import create_fs_tools
from minispark.tools.registry import ToolRegistry
from minispark.tools.function_call.shell import create_shell_tool

__all__ = ["FunctionTool", "ToolRegistry", "create_fs_tools", "create_shell_tool", "tool"]