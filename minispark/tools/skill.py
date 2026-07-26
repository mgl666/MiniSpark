"""use_skill 工具：模型判断任务匹配某技能后，调用它加载该技能的完整指令正文。

技能正文按需加载（渐进式披露）：常驻上下文只有 name + description 摘要，
只有模型主动 use_skill 时正文才进上下文，不吃 token。
"""

from __future__ import annotations

from collections.abc import Mapping

from minispark.tools.skills.loader import Skill
from minispark.tools.base import FunctionTool


def create_skill_tool(skills: Mapping[str, Skill]) -> FunctionTool:
    """按当前技能表创建 use_skill 工具。"""

    def use_skill(name: str) -> str:
        """加载指定技能的完整操作指令（SKILL.md 正文）。

        当用户任务与 system prompt 中列出的某个技能匹配时调用，拿到完整指令后照做。

        :param name: 技能名（见 system prompt 的可用技能列表）
        """
        skill = skills.get(name)
        if skill is None:
            return f"错误：技能 {name!r} 不存在。可用技能：{', '.join(sorted(skills))}"
        return f"# 技能：{skill.name}\n\n{skill.content or '（该技能没有正文指令）'}"

    return FunctionTool(use_skill)