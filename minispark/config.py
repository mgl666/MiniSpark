"""Configuration loading and validation (pydantic v2 + TOML).

A single config.toml controls model, channel, and tool switches — no code changes needed for daily configuration.
"""

from __future__ import annotations

import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # Python 3.10
    import tomli as tomllib
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ProviderConfig(BaseModel):
    """Model provider configuration."""

    base_url: str = "https://api.deepseek.com/v1"
    model: str = "deepseek-chat"
    api_key: str = ""
    """API Key. config.toml is already in .gitignore — do not commit to public repos."""
    model_list: list[str] = []
    """Available model list for /model command display. Empty list hides the candidate list."""


class AgentConfig(BaseModel):
    """Agent core runtime parameters."""

    max_turns: int = 20
    """Maximum tool call rounds per conversation (circuit breaker)."""

    result_char_limit: int = 8000
    """Character limit for truncating a single tool result, prevents context explosion."""

    language: str = "简体中文（用户用其他语言时跟随用户）"
    """Reply language, injected into system prompt."""


class MemoryConfig(BaseModel):
    """Memory system configuration."""

    db_path: str = ""
    """SQLite path. Empty = in-package minispark/memory/minispark.db (default);
    custom paths should use absolute; relative paths resolve from the working directory."""

    recall_top_k: int = 5
    """Maximum number of relevant memories to inject per conversation turn."""

    compact_token_threshold: int = 48000
    """Trigger context compaction when estimated session tokens exceed this value.

    Based on a 64K context window, reserves ~16K headroom (system prompt + output + buffer);
    lower this value for small-window models (e.g. local 8K/32K)."""

    keep_recent_messages: int = 8
    """Number of recent messages to keep as-is during compaction."""

    summary_max_tokens: int = 1000
    """Maximum token count for compaction summary (works for both Chinese and English)."""

    @property
    def resolved_db_path(self) -> Path:
        if not self.db_path:
            return Path(__file__).parent / "memory" / "minispark.db"
        return Path(self.db_path).expanduser()


class EmailChannelConfig(BaseModel):
    """Gmail SMTP email channel configuration.

    Uses Gmail App Password, no OAuth, no external dependencies.
    """

    enabled: bool = False
    sender: str = ""
    """Sender Gmail address."""

    password: str = ""
    """Gmail App Password.
    Generate at: Google Account → Security → 2-Step Verification → App Passwords."""

    to: str = ""
    """Default recipient (scheduled task result push target)."""


class QQBotChannelConfig(BaseModel):
    """QQ Bot channel configuration (Tencent official Bot API)."""

    enabled: bool = False
    """Whether to enable the QQ bot channel."""

    app_id: str = ""
    """QQ Open Platform App ID (Bot ID)."""

    secret: str = ""
    """QQ Bot AppSecret (used for obtaining access_token)."""

    is_sandbox: bool = False
    """Whether to use sandbox environment (true = test, false = production)."""


class ChannelsConfig(BaseModel):
    """Channel switch configuration."""

    cli: bool = True
    qq: QQBotChannelConfig = Field(default_factory=QQBotChannelConfig)
    wechat: bool = False
    email: EmailChannelConfig = Field(default_factory=EmailChannelConfig)


class ToolsConfig(BaseModel):
    """Built-in tools security configuration."""

    allowed_dirs: list[str] = Field(default_factory=lambda: ["."])
    """Directories that file tools are allowed to access (relative to working dir or absolute)."""

    shell_whitelist: list[str] = Field(default_factory=list)
    """Shell pass-through command prefixes (appended to built-in default whitelist)."""

    shell_blacklist: list[str] = Field(default_factory=list)
    """Shell denied command prefixes (appended to built-in default blacklist, highest priority)."""

    shell_require_confirm: bool = True
    """Whether non-whitelist commands require per-command manual confirmation (False = pass-through all, use with caution)."""

    shell_timeout: int = 60
    """Shell command timeout in seconds."""

    def resolved_allowed_dirs(self, base: Path | None = None) -> list[Path]:
        """Resolve allowed directories to absolute path list."""
        base = base or Path.cwd()
        dirs = []
        for d in self.allowed_dirs:
            p = Path(d).expanduser()
            dirs.append((base / p).resolve() if not p.is_absolute() else p.resolve())
        return dirs


class MCPServerConfig(BaseModel):
    """MCP Server configuration entry."""

    name: str
    command: str = ""
    args: list[str] = Field(default_factory=list)
    url: str | None = None


class SchedulerConfig(BaseModel):
    """Scheduled task scheduler configuration."""

    enabled: bool = False
    db_path: str = ""

    @property
    def resolved_db_path(self) -> Path:
        if not self.db_path:
            return Path(__file__).parent / "memory" / "minispark.db"
        return Path(self.db_path).expanduser()


class Config(BaseModel):
    """MiniSpark global configuration."""

    provider: ProviderConfig = Field(default_factory=ProviderConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    mcp_servers: list[MCPServerConfig] = Field(default_factory=list)

    @field_validator("mcp_servers", mode="before")
    @classmethod
    def _normalize_mcp(cls, v: Any) -> Any:
        # Compatible with [[mcp.servers]] syntax in TOML (already normalized by from_toml)
        return v or []

    @classmethod
    def from_toml(cls, path: str | Path) -> Config:
        """Load configuration from a TOML file."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Configuration file not found: {path}")
        with path.open("rb") as f:
            data = tomllib.load(f)
        # Compatible with [[mcp.servers]] -> mcp_servers
        if "mcp" in data and "servers" in data["mcp"]:
            data["mcp_servers"] = data["mcp"]["servers"]
        return cls.model_validate(data)


def load_config(path: str | Path = "config.toml") -> Config:
    """Load configuration file; returns default config if file doesn't exist."""
    path = Path(path)
    if path.exists():
        return Config.from_toml(path)
    return Config()