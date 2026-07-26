"""内置文件工具：read_file / write_file / append_file / edit_file / list_dir。

安全机制：所有路径必须落在 ``config.tools.allowed_dirs`` 白名单目录内。
"""

from __future__ import annotations

from pathlib import Path

from minispark.config import ToolsConfig
from minispark.tools.base import FunctionTool

_MAX_LIST_ENTRIES = 200


class _PathGuard:
    """把用户给的路径解析并校验到白名单目录内。"""

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
        raise PermissionError(f"路径 {p} 不在允许目录内（允许：{allowed_str}）")


def create_fs_tools(config: ToolsConfig) -> list[FunctionTool]:
    """按配置创建文件工具组。"""
    guard = _PathGuard(config.resolved_allowed_dirs())

    def read_file(path: str) -> str:
        """读取文本文件内容（utf-8）。

        :param path: 文件路径（必须在允许目录内）
        """
        try:
            p = guard.resolve(path)
        except PermissionError as exc:
            return f"错误：{exc}"
        if not p.is_file():
            return f"错误：文件不存在或不是普通文件: {p}"
        return p.read_text(encoding="utf-8", errors="replace")

    def write_file(path: str, content: str) -> str:
        """把内容写入文件（自动创建父目录，覆盖写）。

        :param path: 文件路径（必须在允许目录内）
        :param content: 要写入的完整内容
        """
        try:
            p = guard.resolve(path)
        except PermissionError as exc:
            return f"错误：{exc}"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"已写入 {p}（{len(content)} 字符）"

    def append_file(path: str, content: str) -> str:
        """在文件末尾追加内容（自动创建父目录和文件）。

        :param path: 文件路径（必须在允许目录内）
        :param content: 要追加的内容
        """
        try:
            p = guard.resolve(path)
        except PermissionError as exc:
            return f"错误：{exc}"
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(content)
        return f"已追加 {len(content)} 字符到 {p}"

    def edit_file(path: str, old_string: str, new_string: str) -> str:
        """在文件中精确替换一段文本（首次匹配即替换）。

        注意：old_string 必须与文件中的原文完全一致（包括缩进和换行），
        否则匹配失败。只替换首次出现的位置。

        :param path: 文件路径（必须在允许目录内）
        :param old_string: 要被替换的原文（必须精确匹配）
        :param new_string: 替换后的新文本
        """
        try:
            p = guard.resolve(path)
        except PermissionError as exc:
            return f"错误：{exc}"
        if not p.is_file():
            return f"错误：文件不存在: {p}"
        original = p.read_text(encoding="utf-8")
        if old_string not in original:
            return f"错误：未找到匹配的原文，请检查 old_string 是否与文件内容完全一致"
        if original.count(old_string) > 1:
            return f"错误：old_string 匹配到 {original.count(old_string)} 处，请提供更多上下文使匹配唯一"
        updated = original.replace(old_string, new_string, 1)
        p.write_text(updated, encoding="utf-8")
        return f"已修改 {p}（替换 {len(old_string)} → {len(new_string)} 字符）"

    def list_dir(path: str = ".") -> str:
        """列出目录内容，目录名以 / 结尾。

        :param path: 目录路径（必须在允许目录内），默认当前目录
        """
        try:
            p = guard.resolve(path)
        except PermissionError as exc:
            return f"错误：{exc}"
        if not p.is_dir():
            return f"错误：目录不存在: {p}"
        entries = sorted(p.iterdir(), key=lambda e: (e.is_file(), e.name.lower()))
        lines = [(e.name + "/" if e.is_dir() else e.name) for e in entries[:_MAX_LIST_ENTRIES]]
        if len(entries) > _MAX_LIST_ENTRIES:
            lines.append(f"... 其余 {len(entries) - _MAX_LIST_ENTRIES} 项省略")
        return "\n".join(lines) if lines else "(空目录)"

    return [
        FunctionTool(read_file),
        FunctionTool(write_file),
        FunctionTool(append_file),
        FunctionTool(edit_file),
        FunctionTool(list_dir),
    ]