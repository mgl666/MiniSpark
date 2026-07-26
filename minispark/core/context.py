"""上下文组装：system prompt + （M2 记忆 + 技能目录）+ 历史。

M1 阶段只构建 system prompt；记忆注入与上下文压缩在 M2 加入，
M2 同时注入技能目录（只有 name + description 摘要，正文靠 use_skill 按需加载）。
"""

from __future__ import annotations

import platform
from collections.abc import Mapping
from datetime import datetime
from importlib.resources import files
from pathlib import Path

from minispark.config import Config
from minispark.tools.skills.loader import Skill


def _load_system_template() -> str:
    """从 profile/system_profile.md 加载 system prompt 模板。"""
    return (files("minispark") / "profile" / "system_profile.md").read_text(encoding="utf-8")


def build_system_prompt(
    config: Config,
    memories: list[str] | None = None,
    skills: Mapping[str, Skill] | None = None,
) -> str:
    """按当前配置与环境构建 system prompt，并注入相关记忆与技能目录。"""
    allowed = config.tools.resolved_allowed_dirs()
    template = _load_system_template()
    prompt = template.format(
        model=config.provider.model,
        base_url=config.provider.base_url,
        language=config.agent.language,
        os=f"{platform.system()} {platform.release()}",
        cwd=Path.cwd(),
        now=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        allowed_dirs=", ".join(str(d) for d in allowed),
    )
    if memories:
        lines = "\n".join(f"- {m}" for m in memories)
        prompt += f"\n\n## 相关记忆（从历史中检索，可能与本轮相关）\n{lines}"
    if skills:
        lines = "\n".join(f"- {s.name}: {s.description}" for s in skills.values())
        prompt += (
            "\n\n## 可用技能\n"
            "以下是预设的工作流程；当用户任务与某个技能匹配时，先调用 use_skill 工具"
            "加载该技能的完整指令，再严格按指令执行：\n"
            f"{lines}"
        )
    return prompt