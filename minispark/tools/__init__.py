"""工具层：Tool 抽象、注册表、Function Call / Skill / MCP 三种扩展机制。

内置 Function Call 工具在 function_call/ 子目录下（fs / shell / web / memory……），
新增工具在 function_call/ 建一个 .py 文件，写一个带类型注解和 docstring 的函数，
再到 ``core/agent.py`` 的 ``build_default_registry`` 注册即可。
"""

from minispark.tools.base import FunctionTool, tool
from minispark.tools.function_call.fs import create_fs_tools
from minispark.tools.registry import ToolRegistry
from minispark.tools.function_call.shell import create_shell_tool

__all__ = ["FunctionTool", "ToolRegistry", "create_fs_tools", "create_shell_tool", "tool"]