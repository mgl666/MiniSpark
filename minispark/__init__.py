"""MiniSpark - Lightweight personal AI Agent framework.

Library embedding usage::

    from minispark import Agent

    agent = Agent.from_config("config.toml")
    reply = await agent.run("Summarize the code in this directory for me")
"""

from __future__ import annotations

from minispark.config import Config, load_config
from minispark.core.agent import Agent
from minispark.core.session import Session

__version__ = "0.1.0"

__all__ = ["__version__", "Agent", "Session", "Config", "load_config"]