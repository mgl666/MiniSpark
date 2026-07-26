"""MiniSpark - 轻量化个人 AI Agent 框架。

库嵌入用法::

    from minispark import Agent

    agent = Agent.from_config("config.toml")
    reply = await agent.run("帮我总结这个目录下的代码")
"""

from __future__ import annotations

from minispark.config import Config, load_config
from minispark.core.agent import Agent
from minispark.core.session import Session

__version__ = "0.1.0"

__all__ = ["__version__", "Agent", "Session", "Config", "load_config"]
