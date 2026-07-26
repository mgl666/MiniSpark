"""内置 Shell 工具：run_shell。

三级安全策略：
1. 黑名单 —— 内置高危模式 + 配置追加，直接拒绝；
2. 白名单 —— 内置只读常用命令 + 配置追加，直接放行；
3. 其余命令 —— 需人工确认（CLI 弹确认，由通道注入 confirm 回调）。
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable

from minispark.config import ToolsConfig
from minispark.tools.base import FunctionTool

logger = logging.getLogger(__name__)

# 内置黑名单：命中即拒绝（子串匹配，不区分大小写）
DEFAULT_BLACKLIST = [
    "rm -rf /",
    "rm -rf ~",
    "rm -rf *",
    "mkfs",
    ":(){",
    "dd if=",
    "> /dev/",
    "format c:",
    "format d:",
    "del /f /s /q c:",
    "rd /s /q c:\\",
    "shutdown",
    "reboot",
    "diskpart",
    "bcdedit",
    "reg delete",
    "curl ",
    "wget ",
    "powershell -enc",
    "Invoke-Expression",
]

# 内置白名单：只读常用命令前缀，前缀匹配即放行
DEFAULT_WHITELIST = [
    "ls",
    "dir",
    "pwd",
    "echo",
    "cat",
    "type",
    "head",
    "tail",
    "find",
    "grep",
    "tree",
    "git status",
    "git log",
    "git diff",
    "git show",
    "git branch",
    "python --version",
    "python -V",
    "pip list",
    "pip show",
    "pip freeze",
    "conda list",
    "conda env list",
    "where ",
    "which ",
    "whoami",
    "hostname",
    "date",
    "time",
    "systeminfo | findstr",
]

ConfirmFn = Callable[[str], bool | Awaitable[bool]]


def _normalize(command: str) -> str:
    return re.sub(r"\s+", " ", command.strip()).lower()


def create_shell_tool(config: ToolsConfig, confirm: ConfirmFn | None = None) -> FunctionTool:
    """按配置创建 shell 工具，confirm 为通道注入的确认回调。"""
    blacklist = DEFAULT_BLACKLIST + [_normalize(p) for p in config.shell_blacklist]
    whitelist = DEFAULT_WHITELIST + [_normalize(p) for p in config.shell_whitelist]

    def classify(command: str) -> str:
        """返回 black / white / gray。"""
        norm = _normalize(command)
        if any(pattern in norm for pattern in blacklist):
            return "black"
        if any(norm == w or norm.startswith(w + " ") or norm.startswith(w) for w in whitelist):
            return "white"
        return "gray"

    async def run_shell(command: str) -> str:
        """执行 Shell 命令并返回输出（黑名单拒绝、白名单直通、其余需确认）。

        :param command: 要执行的完整命令
        """
        level = classify(command)
        if level == "black":
            logger.warning("拒绝执行黑名单命令: %s", command)
            return "错误：该命令命中黑名单，已被拒绝执行。"
        if level == "gray" and config.shell_require_confirm:
            if confirm is None:
                return "错误：该命令需要人工确认，但当前通道未提供确认机制，已拒绝执行。"
            if asyncio.iscoroutinefunction(confirm):
                approved = await confirm(command)
            else:
                # 同步回调（如 CLI 弹窗）放到线程里跑，避免阻塞事件循环
                approved = await asyncio.to_thread(confirm, command)
            if not approved:
                return "错误：用户拒绝了该命令的执行。"

        logger.info("执行命令: %s", command)
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            try:
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=config.shell_timeout)
            except (asyncio.TimeoutError, TimeoutError):  # 3.10 中二者不同类
                proc.kill()
                await proc.wait()
                return f"错误：命令执行超时（>{config.shell_timeout}s），已终止。"
        except OSError as exc:
            return f"错误：命令启动失败: {exc}"

        output = stdout.decode("utf-8", errors="replace").strip()
        header = f"[exit code: {proc.returncode}]"
        return f"{header}\n{output}" if output else header

    return FunctionTool(run_shell)