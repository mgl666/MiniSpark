"""Built-in file tools: read_file / write_file / append_file / edit_file / list_dir.

Security: all paths must fall within the ``config.tools.allowed_dirs`` whitelist directories.
"""

from __future__ import annotations

from pathlib import Path

from minispark.config import ToolsConfig
from minispark.tools.base import FunctionTool

_MAX_LIST_ENTRIES = 200


class _PathGuard:
    """Resolve user-provided paths and validate within whitelist directories."""

    def __init__(self, allowed_dirs: list[Path]) -> None:
        self._allowed = allowed_dirs

    def resolve(self, path: str) -> Path:
        p = Path(path).expanduser()
        if not p.is_absolute():
            p = Path.cwd() / p
        p = p.resolve()
        for allowed in self._allowed:
            if p == allowed or allowed in p.parents:
                return p
        allowed_str = ", ".join(str(d) for d in self._allowed)
        raise PermissionError(f"Path {p} is not within allowed directories (allowed: {allowed_str})")


def create_fs_tools(config: ToolsConfig) -> list[FunctionTool]:
    """Create file tool group based on configuration."""
    guard = _PathGuard(config.resolved_allowed_dirs())

    def read_file(path: str) -> str:
        """Read text file content (utf-8).

        :param path: File path (must be within allowed directories)
        """
        try:
            p = guard.resolve(path)
        except PermissionError as exc:
            return f"Error: {exc}"
        if not p.is_file():
            return f"Error: File does not exist or is not a regular file: {p}"
        return p.read_text(encoding="utf-8", errors="replace")

    def write_file(path: str, content: str) -> str:
        """Write content to a file (auto-create parent directories, overwrite).

        :param path: File path (must be within allowed directories)
        :param content: Full content to write
        """
        try:
            p = guard.resolve(path)
        except PermissionError as exc:
            return f"Error: {exc}"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Written to {p} ({len(content)} chars)"

    def append_file(path: str, content: str) -> str:
        """Append content to the end of a file (auto-create parent directories and file).

        :param path: File path (must be within allowed directories)
        :param content: Content to append
        """
        try:
            p = guard.resolve(path)
        except PermissionError as exc:
            return f"Error: {exc}"
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(content)
        return f"Appended {len(content)} chars to {p}"

    def edit_file(path: str, old_string: str, new_string: str) -> str:
        """Precisely replace a block of text in a file (first match only).

        Note: old_string must match the file content exactly (including indentation and newlines),
        otherwise the match will fail. Only the first occurrence is replaced.

        :param path: File path (must be within allowed directories)
        :param old_string: The original text to be replaced (must match exactly)
        :param new_string: The replacement text
        """
        try:
            p = guard.resolve(path)
        except PermissionError as exc:
            return f"Error: {exc}"
        if not p.is_file():
            return f"Error: File does not exist: {p}"
        original = p.read_text(encoding="utf-8")
        if old_string not in original:
            return f"Error: No matching text found, please check that old_string matches the file content exactly"
        if original.count(old_string) > 1:
            return f"Error: old_string matches {original.count(old_string)} occurrences, please provide more context for a unique match"
        updated = original.replace(old_string, new_string, 1)
        p.write_text(updated, encoding="utf-8")
        return f"Modified {p} (replaced {len(old_string)} -> {len(new_string)} chars)"

    def list_dir(path: str = ".") -> str:
        """List directory contents, directories end with /.

        :param path: Directory path (must be within allowed directories), defaults to current directory
        """
        try:
            p = guard.resolve(path)
        except PermissionError as exc:
            return f"Error: {exc}"
        if not p.is_dir():
            return f"Error: Directory does not exist: {p}"
        entries = sorted(p.iterdir(), key=lambda e: (e.is_file(), e.name.lower()))
        lines = [(e.name + "/" if e.is_dir() else e.name) for e in entries[:_MAX_LIST_ENTRIES]]
        if len(entries) > _MAX_LIST_ENTRIES:
            lines.append(f"... {len(entries) - _MAX_LIST_ENTRIES} more entries omitted")
        return "\n".join(lines) if lines else "(empty directory)"

    return [
        FunctionTool(read_file),
        FunctionTool(write_file),
        FunctionTool(append_file),
        FunctionTool(edit_file),
        FunctionTool(list_dir),
    ]