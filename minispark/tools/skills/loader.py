"""Skill loader: scan skill directories, parse SKILL.md, produce skill table.

A skill = a folder containing SKILL.md (frontmatter declaring name/description + Markdown instruction body).
Skills are essentially prompts: only a one-line summary (name + description) stays in context,
the model loads the full body via use_skill when a task matches (progressive disclosure, inspired by Hermes / Claude Code Skill patterns).

All skills are placed under the package's minispark/tools/skills/library/ directory, one folder per skill.
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
    """A parsed skill."""

    name: str
    description: str
    content: str
    """SKILL.md instruction body after removing frontmatter."""
    triggers: list[str] = field(default_factory=list)
    path: str = ""
    """Source file path, for user reference."""


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse a minimal subset of YAML frontmatter: flat ``key: value`` and ``- `` lists.

    No PyYAML dependency: skill metadata only needs these two patterns. Returns (meta, body).
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
    """Recursively load skills from a directory. ``base`` is a Path or importlib.resources Traversable."""
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
            logger.warning("Skill %s missing description, skipping (%s)", name, skill_file)
            continue
        if name in into:
            logger.warning("Skill %s duplicate name: %s overwrites %s", name, skill_file, into[name].path)
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
    """Scan the skills directory and return a name -> Skill dictionary.

    :param skills_dir: Skills directory, defaults to package's minispark/tools/skills/ (tests can pass a temp dir).
    """
    skills: dict[str, Skill] = {}
    _load_from(skills_dir or files("minispark.tools.skills"), skills)
    return skills