"""MiniSpark CLI 入口（typer 命令薄壳）。

子命令：init / chat / serve / cron / qq / qq-stop / qq-status
终端对话的实现在 channels/cli.py，这里只做命令分发与日志初始化。
"""

from __future__ import annotations

import asyncio
import json
import logging
import logging.handlers
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from minispark.config import load_config

console = Console()

app = typer.Typer(
    name="minispark",
    help="MiniSpark - 轻量化个人 AI Agent 框架",
    no_args_is_help=True,
)

cron_app = typer.Typer(help="定时任务管理")
app.add_typer(cron_app, name="cron")


def setup_logging(verbose: bool = False, *, log_name: str = "cli") -> None:
    """使用 rich 配置日志输出（终端 + 轮转文件）。"""
    level = logging.DEBUG if verbose else logging.INFO

    log_dir = Path.home() / ".minispark"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{log_name}.log"

    file_handler = logging.handlers.RotatingFileHandler(
        str(log_file),
        maxBytes=20 * 1024 * 1024,
        backupCount=0,
        encoding="utf-8",
    )
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[
            RichHandler(rich_tracebacks=True, show_path=False),
            file_handler,
        ],
    )
    if not verbose:
        for name in ("httpx", "httpcore", "openai"):
            logging.getLogger(name).setLevel(logging.WARNING)


@app.callback()
def main(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="输出调试日志"),
) -> None:
    """MiniSpark - 轻量化个人 AI Agent 框架。"""
    setup_logging(verbose=verbose, log_name="cli")


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


# ── 后台进程管理工具 ──────────────────────────────────


def _get_pid_dir() -> Path:
    """获取 PID 文件存放目录。"""
    pid_dir = Path.home() / ".minispark"
    pid_dir.mkdir(parents=True, exist_ok=True)
    return pid_dir


def _get_pid_path() -> Path:
    """获取 QQ 机器人的 PID 文件路径。"""
    return _get_pid_dir() / "qq.pid"


def _get_log_path() -> Path:
    """获取 QQ 机器人的后台日志路径。"""
    return _get_pid_dir() / "qq.log"


def _read_pid_file() -> dict | None:
    """读取 PID 文件，返回进程信息字典；文件不存在或格式错误返回 None。"""
    pid_path = _get_pid_path()
    if not pid_path.exists():
        return None
    try:
        return json.loads(pid_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write_pid_file(pid: int, config_path: str) -> None:
    """写入 PID 文件。"""
    info = {
        "pid": pid,
        "config_path": config_path,
        "started_at": datetime.now().isoformat(),
    }
    _get_pid_path().write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")


def _remove_pid_file() -> None:
    """删除 PID 文件。"""
    pid_path = _get_pid_path()
    if pid_path.exists():
        pid_path.unlink()


def _is_process_running(pid: int) -> bool:
    """检查指定 PID 的进程是否仍在运行。"""
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        SYNCHRONIZE = 0x00100000
        handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False


def _spawn_background(config_path: Path) -> int:
    """在后台启动 QQ 机器人子进程，返回子进程 PID。

    在 Windows 上使用 pythonw.exe（无控制台窗口），
    在 Unix 上使用 start_new_session 实现终端脱离。
    日志由子进程的 RotatingFileHandler 写入 qq.log。
    """
    if sys.platform == "win32":
        pythonw = sys.executable.replace("python.exe", "pythonw.exe")
        if not os.path.exists(pythonw):
            pythonw = sys.executable

        proc = subprocess.Popen(
            [
                pythonw,
                "-m",
                "minispark",
                "qq",
                "--config",
                str(config_path),
                "--daemon",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return proc.pid
    else:
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "minispark",
                "qq",
                "--config",
                str(config_path),
                "--daemon",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        return proc.pid


@app.command()
def qq(
    config_path: Path = typer.Option(Path("config.toml"), "--config", "-c", help="配置文件路径"),
    background: bool = typer.Option(False, "--background", "-b", help="后台静默运行（不占用终端）"),
    daemon: bool = typer.Option(False, "--daemon", hidden=True, help="内部使用：以守护进程模式运行"),
) -> None:
    """启动 QQ 机器人通道（腾讯官方 Bot API）。

    直接运行将占用当前终端，按 Ctrl+C 停止。
    使用 --background / -b 参数将在后台静默运行，不占用终端窗口。
    """
    if background:
        info = _read_pid_file()
        if info and _is_process_running(info["pid"]):
            console.print(
                f"[yellow]QQ 机器人已在后台运行中（PID: {info['pid']}，"
                f"启动时间: {info.get('started_at', '未知')}）[/yellow]"
            )
            console.print("[dim]如需重启请先执行 python -m minispark qq-stop[/dim]")
            raise SystemExit(1)

        _remove_pid_file()
        pid = _spawn_background(config_path)
        _write_pid_file(pid, str(config_path))

        console.print(f"[green]QQ 机器人已在后台启动[/green]")
        console.print(f"  PID: {pid}")
        console.print(f"  日志: {_get_log_path()}")
        console.print(f"  配置: {config_path}")
        console.print()
        console.print("[dim]管理命令:[/dim]")
        console.print("  python -m minispark qq-status   查看运行状态")
        console.print("  python -m minispark qq-stop     停止后台运行")
        return

    if daemon:
        setup_logging(verbose=False, log_name="qq")
        from minispark.channels.qq import run_qq_bot

        asyncio.run(run_qq_bot(load_config(config_path), config_path, daemon=True))
        return

    from minispark.channels.qq import run_qq_bot

    asyncio.run(run_qq_bot(load_config(config_path), config_path))


@app.command(name="qq-stop")
def qq_stop() -> None:
    """停止后台运行的 QQ 机器人。"""
    info = _read_pid_file()
    if info is None:
        console.print("[yellow]没有找到 QQ 机器人的后台进程记录[/yellow]")
        return

    pid = info["pid"]
    if not _is_process_running(pid):
        console.print(f"[yellow]PID {pid} 对应的进程已不存在（可能已自动退出）[/yellow]")
        _remove_pid_file()
        return

    try:
        if sys.platform == "win32":
            os.kill(pid, signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGTERM)

        for _ in range(50):
            if not _is_process_running(pid):
                break
            time.sleep(0.1)
        else:
            if sys.platform != "win32":
                console.print(f"[yellow]进程未响应 SIGTERM，强制终止...[/yellow]")
                os.kill(pid, signal.SIGKILL)
                time.sleep(0.5)

        if _is_process_running(pid):
            console.print(f"[red]无法终止进程 PID {pid}[/red]")
        else:
            console.print(f"[green]QQ 机器人已停止（PID: {pid}）[/green]")
            _remove_pid_file()
            console.print(f"  日志文件: {_get_log_path()}")
    except OSError:
        console.print(f"[yellow]PID {pid} 对应的进程已不存在（可能已自动退出）[/yellow]")
        _remove_pid_file()
    except Exception as e:
        console.print(f"[red]停止失败: {e}[/red]")


@app.command(name="qq-status")
def qq_status() -> None:
    """查看 QQ 机器人后台运行状态。"""
    info = _read_pid_file()

    table = Table(title="QQ 机器人后台状态")
    table.add_column("项目", style="cyan", no_wrap=True)
    table.add_column("值", style="white")

    if info is None:
        table.add_row("状态", "[yellow]未运行（没有 PID 文件）[/yellow]")
        console.print(table)
        return

    pid = info["pid"]
    running = _is_process_running(pid)

    table.add_row("状态", "[green]运行中[/green]" if running else "[red]已停止[/red]")
    table.add_row("PID", str(pid))
    table.add_row("启动时间", info.get("started_at", "未知"))
    table.add_row("配置文件", info.get("config_path", "未知"))
    table.add_row("日志文件", str(_get_log_path()))
    table.add_row("PID 文件", str(_get_pid_path()))

    console.print(table)

    if not running:
        console.print()
        console.print("[yellow]提示: 进程已不在运行，可执行 python -m minispark qq-stop 清理 PID 文件[/yellow]")


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