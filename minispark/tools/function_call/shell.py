"""Built-in Shell tool: run_shell.

Three-tier security policy:
1. Blacklist — built-in high-risk patterns + config additions, immediately denied;
2. Whitelist — built-in read-only common commands + config additions, pass-through;
3. Other commands — require manual confirmation (CLI prompts, channel injects confirm callback).
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable

from minispark.config import ToolsConfig
from minispark.tools.base import FunctionTool

logger = logging.getLogger(__name__)

# Built-in blacklist: match = deny (substring match, case-insensitive)
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

# Built-in whitelist: read-only common command prefixes, prefix match = pass-through
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
    """Create shell tool based on config, confirm is the channel-injected confirmation callback."""
    blacklist = DEFAULT_BLACKLIST + [_normalize(p) for p in config.shell_blacklist]
    whitelist = DEFAULT_WHITELIST + [_normalize(p) for p in config.shell_whitelist]

    def classify(command: str) -> str:
        """Return black / white / gray."""
        norm = _normalize(command)
        if any(pattern in norm for pattern in blacklist):
            return "black"
        if any(norm == w or norm.startswith(w + " ") or norm.startswith(w) for w in whitelist):
            return "white"
        return "gray"

    async def run_shell(command: str) -> str:
        """Execute a shell command and return output (blacklist denied, whitelist pass-through, others require confirmation).

        :param command: The full command to execute
        """
        level = classify(command)
        if level == "black":
            logger.warning("Denied blacklist command: %s", command)
            return "Error: This command matches the blacklist and has been denied."
        if level == "gray" and config.shell_require_confirm:
            if confirm is None:
                return "Error: This command requires manual confirmation, but the current channel does not provide a confirmation mechanism. Execution denied."
            if asyncio.iscoroutinefunction(confirm):
                approved = await confirm(command)
            else:
                # Sync callback (e.g. CLI prompt) runs in a thread to avoid blocking the event loop
                approved = await asyncio.to_thread(confirm, command)
            if not approved:
                return "Error: User denied the execution of this command."

        logger.info("Executing command: %s", command)
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            try:
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=config.shell_timeout)
            except (asyncio.TimeoutError, TimeoutError):  # Different classes in 3.10
                proc.kill()
                await proc.wait()
                return f"Error: Command execution timed out (>{config.shell_timeout}s), terminated."
        except OSError as exc:
            return f"Error: Command failed to start: {exc}"

        output = stdout.decode("utf-8", errors="replace").strip()
        header = f"[exit code: {proc.returncode}]"
        return f"{header}\n{output}" if output else header

    return FunctionTool(run_shell)