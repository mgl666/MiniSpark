"""配置加载与校验（pydantic v2 + TOML）。

一个 config.toml 控制模型、通道、工具开关，不写代码即可完成日常配置。
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
    """模型供应商配置。"""

    base_url: str = "https://api.deepseek.com/v1"
    model: str = "deepseek-chat"
    api_key: str = ""
    """API Key。config.toml 已在 .gitignore 中，勿提交公开仓库。"""
    model_list: list[str] = []
    """可用模型列表，供 /model 命令展示。空列表则不显示候选清单。"""


class AgentConfig(BaseModel):
    """Agent 核心运行参数。"""

    max_turns: int = 20
    """单次对话最大工具调用轮数（熔断值）。"""

    result_char_limit: int = 8000
    """单条工具结果截断字符数，防止上下文爆炸。"""

    language: str = "简体中文（用户用其他语言时跟随用户）"
    """回复语言，注入 system prompt。"""


class MemoryConfig(BaseModel):
    """记忆系统配置。"""

    db_path: str = ""
    """SQLite 路径。留空 = 包内 minispark/memory/minispark.db（默认）；
    自定义建议用绝对路径，相对路径按启动目录解析。"""

    recall_top_k: int = 5
    """每轮对话注入的相关记忆条数上限。"""

    compact_token_threshold: int = 48000
    """会话估算 token 超过该值时触发上下文压缩。

    按 64K 上下文窗口预留约 16K 余量（system prompt + 输出 + 缓冲）；
    用小窗口模型（如本地 8K/32K）时应相应调低。"""

    keep_recent_messages: int = 8
    """压缩时原样保留的最近消息条数。"""

    summary_max_tokens: int = 1000
    """压缩摘要的最大 token 数（中文英文通用）。"""

    @property
    def resolved_db_path(self) -> Path:
        if not self.db_path:
            return Path(__file__).parent / "memory" / "minispark.db"
        return Path(self.db_path).expanduser()


class EmailChannelConfig(BaseModel):
    """Gmail SMTP 邮件通道配置。

    使用 Gmail 应用专用密码，无需 OAuth，无需任何外部依赖。
    """

    enabled: bool = False
    sender: str = ""
    """发件人 Gmail 地址。"""

    password: str = ""
    """Gmail 应用专用密码。
    在 Google 账号 → 安全性 → 两步验证 → 应用专用密码 中生成。"""

    to: str = ""
    """默认收件人（定时任务结果推送目标）。"""


class QQBotChannelConfig(BaseModel):
    """QQ 机器人通道配置（腾讯官方 Bot API）。"""

    enabled: bool = False
    """是否启用 QQ 机器人通道。"""

    app_id: str = ""
    """QQ 开放平台应用 ID（机器人 ID）。"""

    secret: str = ""
    """QQ 机器人 AppSecret（用于获取 access_token）。"""

    is_sandbox: bool = False
    """是否使用沙箱环境（true 为测试环境，false 为正式环境）。"""


class ChannelsConfig(BaseModel):
    """通道开关配置。"""

    cli: bool = True
    qq: QQBotChannelConfig = Field(default_factory=QQBotChannelConfig)
    wechat: bool = False
    email: EmailChannelConfig = Field(default_factory=EmailChannelConfig)


class ToolsConfig(BaseModel):
    """内置工具安全配置。"""

    allowed_dirs: list[str] = Field(default_factory=lambda: ["."])
    """文件工具允许访问的目录（相对启动目录或绝对路径）。"""

    shell_whitelist: list[str] = Field(default_factory=list)
    """Shell 直通命令前缀（在内置默认白名单之外追加）。"""

    shell_blacklist: list[str] = Field(default_factory=list)
    """Shell 拒绝命令前缀（在内置默认黑名单之外追加，优先级最高）。"""

    shell_require_confirm: bool = True
    """非白名单命令是否逐条人工确认（False 则全部直通，慎用）。"""

    shell_timeout: int = 60
    """Shell 命令超时秒数。"""

    def resolved_allowed_dirs(self, base: Path | None = None) -> list[Path]:
        """把允许目录解析为绝对路径列表。"""
        base = base or Path.cwd()
        dirs = []
        for d in self.allowed_dirs:
            p = Path(d).expanduser()
            dirs.append((base / p).resolve() if not p.is_absolute() else p.resolve())
        return dirs


class MCPServerConfig(BaseModel):
    """MCP Server 配置项。"""

    name: str
    command: str = ""
    args: list[str] = Field(default_factory=list)
    url: str | None = None


class SchedulerConfig(BaseModel):
    """定时任务调度器配置。"""

    enabled: bool = False
    db_path: str = ""

    @property
    def resolved_db_path(self) -> Path:
        if not self.db_path:
            return Path(__file__).parent / "memory" / "minispark.db"
        return Path(self.db_path).expanduser()


class Config(BaseModel):
    """MiniSpark 全局配置。"""

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
        # 兼容 TOML 里 [[mcp.servers]] 写法（已由 from_toml 归一化）
        return v or []

    @classmethod
    def from_toml(cls, path: str | Path) -> Config:
        """从 TOML 文件加载配置。"""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"配置文件不存在: {path}")
        with path.open("rb") as f:
            data = tomllib.load(f)
        # 兼容 [[mcp.servers]] -> mcp_servers
        if "mcp" in data and "servers" in data["mcp"]:
            data["mcp_servers"] = data["mcp"]["servers"]
        return cls.model_validate(data)


def load_config(path: str | Path = "config.toml") -> Config:
    """加载配置文件，不存在时返回默认配置。"""
    path = Path(path)
    if path.exists():
        return Config.from_toml(path)
    return Config()