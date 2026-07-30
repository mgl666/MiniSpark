"""use_skill tool: when the model determines a task matches a skill, it calls this to load the full instruction body.

Skills are loaded on-demand (progressive disclosure): only name + description summaries stay in context,
the full body only enters context when the model proactively calls use_skill, saving tokens.
"""

from __future__ import annotations

from collections.abc import Mapping

from minispark.tools.skills.loader import Skill
from minispark.tools.base import FunctionTool


def create_skill_tool(skills: Mapping[str, Skill]) -> FunctionTool:
    """Create a use_skill tool based on the current skill table."""

    def use_skill(name: str) -> str:
        """Load the full instruction body (SKILL.md content) of a specified skill.

        Call this when the user's task matches a skill listed in the system prompt,
        then follow the loaded instructions.

        :param name: Skill name (see the available skills list in the system prompt)
        """
        skill = skills.get(name)
        if skill is None:
            return f"Error: Skill {name!r} does not exist. Available skills: {', '.join(sorted(skills))}"
        return f"# Skill: {skill.name}\n\n{skill.content or '(This skill has no instruction body)'}"

    return FunctionTool(use_skill)