"""MiniSpark CLI 入口（typer 命令薄壳）。

子命令：init / chat / serve / cron
终端对话的实现在 channels/cli.py，这里只做命令分发与日志初始化。
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import typer
from rich.logging import RichHandler

from minispark.config import load_config

app = typer.Typer(
    name="minispark",
    help="MiniSpark - 轻量化个人 AI Agent 框架",
    no_args_is_help=True,
)

cron_app = typer.Typer(help="定时任务管理")
app.add_typer(cron_app, name="cron")


def setup_logging(verbose: bool = False) -> None:
    """使用 rich 配置日志输出。"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, show_path=False)],
    )
    # 第三方库的 HTTP 请求日志（"HTTP Request: POST ..."）太吵，
    # 非调试模式下压到 WARNING，只保留 minispark 自己的日志
    if not verbose:
        for name in ("httpx", "httpcore", "openai"):
            logging.getLogger(name).setLevel(logging.WARNING)


@app.callback()
def main(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="输出调试日志"),
) -> None:
    """MiniSpark - 轻量化个人 AI Agent 框架。"""
    setup_logging(verbose=verbose)


@app.command()
def init(
    config_path: Path = typer.Option(
        Path("config.toml"), "--config", "-c", help="配置文件输出路径"
    ),
) -> None:
    """交互式生成配置文件。"""
    typer.echo(f"TODO: 生成配置文件到 {config_path}（M4 实现）")


@app.command()
def chat(
    config_path: Path = typer.Option(Path("config.toml"), "--config", "-c", help="配置文件路径"),
) -> None:
    """启动终端对话。"""
    from minispark.channels.cli import run_cli_channel

    asyncio.run(run_cli_channel(load_config(config_path), config_path))


@app.command()
def qq(
    config_path: Path = typer.Option(Path("config.toml"), "--config", "-c", help="配置文件路径"),
) -> None:
    """启动 QQ 机器人通道（腾讯官方 Bot API）。"""
    from minispark.channels.qq import run_qq_bot

    asyncio.run(run_qq_bot(load_config(config_path), config_path))


@app.command()
def serve(
    config_path: Path = typer.Option(Path("config.toml"), "--config", "-c", help="配置文件路径"),
) -> None:
    """常驻模式：启动 Gateway + Scheduler，接管消息平台。"""
    typer.echo("TODO: 启动 serve（M3 实现）")


@cron_app.command("add")
def cron_add() -> None:
    """添加定时任务。"""
    typer.echo("TODO: cron add（M3 实现）")


@cron_app.command("list")
def cron_list() -> None:
    """列出定时任务。"""
    typer.echo("TODO: cron list（M3 实现）")


@cron_app.command("remove")
def cron_remove(
    task_id: str = typer.Argument(..., help="任务 ID"),
) -> None:
    """删除定时任务。"""
    typer.echo(f"TODO: cron remove {task_id}（M3 实现）")


if __name__ == "__main__":
    app()