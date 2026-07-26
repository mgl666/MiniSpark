"""Skill 加载器：扫描技能目录、解析 SKILL.md，产出技能表。

一个技能 = 一个文件夹，内含 SKILL.md（frontmatter 声明 name/description + Markdown 指令正文）。
技能本质是 prompt：常驻上下文只有 name + description 一行摘要，模型判断任务匹配时
通过 use_skill 工具加载完整正文（渐进式披露，参考 Hermes / Claude Code 的 Skill 形态）。

所有技能统一放在包内 minispark/tools/skills/library/ 目录下，一个技能一个文件夹。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SKILL_FILENAME = "SKILL.md"
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)


@dataclass
class Skill:
    """一个已解析的技能。"""

    name: str
    description: str
    content: str
    """SKILL.md 去掉 frontmatter 后的指令正文。"""
    triggers: list[str] = field(default_factory=list)
    path: str = ""
    """来源文件路径，便于用户定位修改。"""


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """解析 YAML frontmatter 的最小子集：平铺 ``key: value`` 与 ``- `` 列表。

    不引入 PyYAML：技能元数据只需要这两样。返回 (meta, 正文)。
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text.strip()
    meta_block, body = match.group(1), match.group(2).strip()
    meta: dict[str, Any] = {}
    last_key = ""
    for raw_line in meta_block.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("- ") and last_key:
            existing = meta.get(last_key)
            if not isinstance(existing, list):
                existing = [existing] if existing else []
                meta[last_key] = existing
            existing.append(_unquote(line[2:].strip()))
            continue
        key, sep, value = line.partition(":")
        if not sep:
            continue
        last_key = key.strip()
        meta[last_key] = _unquote(value.strip())
    return meta, body


def _load_from(base: Any, into: dict[str, Skill]) -> None:
    """从一个目录递归加载技能。``base`` 是 Path 或 importlib.resources 的 Traversable。"""
    try:
        entries = sorted(base.iterdir(), key=lambda e: e.name)
    except (FileNotFoundError, NotADirectoryError, OSError):
        return
    for entry in entries:
        if not entry.is_dir():
            continue
        skill_file = entry / _SKILL_FILENAME
        try:
            text = skill_file.read_text(encoding="utf-8")
        except (FileNotFoundError, OSError):
            _load_from(entry, into)
            continue
        meta, body = _parse_frontmatter(text)
        name = str(meta.get("name") or entry.name).strip()
        description = str(meta.get("description") or "").strip()
        if not description:
            logger.warning("技能 %s 缺少 description，跳过（%s）", name, skill_file)
            continue
        if name in into:
            logger.warning("技能 %s 重名：%s 覆盖 %s", name, skill_file, into[name].path)
        triggers = meta.get("triggers") or []
        if isinstance(triggers, str):
            triggers = [triggers]
        into[name] = Skill(
            name=name,
            description=description,
            content=body,
            triggers=[str(t) for t in triggers],
            path=str(skill_file),
        )


def discover_skills(skills_dir: Path | None = None) -> dict[str, Skill]:
    """扫描技能目录，返回 name -> Skill 字典。

    :param skills_dir: 技能目录，默认包内 minispark/tools/skills/（测试可传临时目录）。
    """
    skills: dict[str, Skill] = {}
    _load_from(skills_dir or files("minispark.tools.skills"), skills)
    return skills