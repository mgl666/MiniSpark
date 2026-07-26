"""终端交互通道：REPL 循环、rich 渲染、shell 人工确认、会话管理斜杠命令。

开发/调试必备入口，由 ``minispark chat`` 命令启动。
M3 接入 Gateway 后与其他通道共用 ``channels/base.py`` 的抽象。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.console import Console, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.status import Status
from rich.text import Text

from minispark.config import Config

if TYPE_CHECKING:
    from minispark.core.agent import Agent
    from minispark.core.session import Session
    from minispark.memory.store import MemoryStore

console = Console()

_SLASH_HELP = """[bold]会话命令[/bold]
  /new [名称]     开新会话（长期记忆保留，历史清零）
  /sessions       列出所有会话
  /load <名称>    切换到指定会话
  /delete <名称>  删除指定会话的历史
  /history [n]    查看当前会话最近 n 条消息（默认 10）
  /compact        强制压缩当前会话上下文（旧消息摘要化）
[bold]记忆命令[/bold]
  /memory         查看所有长期记忆
  /forget <编号>  删除指定编号的长期记忆
[bold]调试命令[/bold]
  /tools_list            列出所有已注册的 Function Call 工具
  /skills_list           列出所有已发现的技能
  /cron_list             查看所有定时任务
  /cron_cancel <ID>      取消指定定时任务（ID 从 /cron_list 获取）
  /model [名称]          查看或切换模型（不传名称则显示当前模型）
  /gmail_verification    手动触发 Gmail OAuth 2.0 授权
  /help                  显示本帮助
  exit / quit     退出"""


def confirm_shell(command: str) -> bool:
    """CLI 通道的 shell 确认回调。"""
    console.print(f"[yellow]Agent 请求执行命令：[/yellow] [bold]{command}[/bold]")
    return Confirm.ask("允许执行？", default=False)


class _StatusLogHandler(logging.Handler):
    """把日志记录转成状态栏文本：思考时可见，思考结束随状态栏一起消失。"""

    def __init__(self, status: Status) -> None:
        super().__init__()
        self._status = status

    def emit(self, record: logging.LogRecord) -> None:
        self._status.update(f"[dim]{record.getMessage()}[/dim]")


async def _run_with_status(agent: Agent, text: str, session: Session) -> str:
    """带状态栏运行 Agent：日志实时滚到状态栏，结束后不留痕。

    调试模式（-v）下保持原样：日志经常驻 handler 打印留痕，便于排查。
    """
    verbose = logging.getLogger("minispark").getEffectiveLevel() <= logging.DEBUG
    ms_logger = logging.getLogger("minispark")
    status = console.status("思考中...", spinner="dots")
    handler = _StatusLogHandler(status)
    if not verbose:
        ms_logger.addHandler(handler)
        ms_logger.propagate = False  # 阻止日志落到常驻 RichHandler
    try:
        with status:
            return await agent.run(text, session)
    finally:
        if not verbose:
            ms_logger.removeHandler(handler)
            ms_logger.propagate = True


def _print_banner(config: Config, agent: Agent, email_channel: Any = None) -> None:
    scheduler_status = "已启动" if (agent.scheduler and agent.scheduler.running) else "未启动"
    lines = [
        Text("MiniSpark Chat", style="bold cyan", justify="center"),
        Text(f"model: {config.provider.model}", justify="center"),
        Text(
            f"tools: {len(agent.registry)}  "
            f"skills: {len(agent.skills)}  "
            f"mcp: {len(config.mcp_servers)}",
            justify="center",
        ),
        Text(f"scheduler: {scheduler_status}", justify="center"),
    ]
    if email_channel is not None:
        lines.append(
            Text(
                f"email: {config.channels.email.sender} ({'可用' if email_channel.is_ready else '不可用'})",
                justify="center",
            )
        )
    if config.channels.qq.enabled:
        lines.append(
            Text(
                f"qq: {'沙箱' if config.channels.qq.is_sandbox else '正式'}",
                justify="center",
            )
        )
    banner = Group(*lines)
    console.print(Panel(banner, border_style="cyan", width=min(100, console.width)))


def _show_history(session: Session, limit: int = 10) -> None:
    """打印当前会话最近 limit 条消息。"""
    msgs = session.messages[-limit:] if limit > 0 else session.messages
    if not msgs:
        console.print("[dim]（当前会话暂无历史）[/dim]")
        return
    label = {"user": "你", "assistant": "MiniSpark", "tool": "工具"}
    style = {"user": "green", "assistant": "blue", "tool": "dim"}
    for m in msgs:
        role = str(m.get("role"))
        content = str(m.get("content") or "").replace("\n", " ")
        if len(content) > 100:
            content = content[:100] + "…"
        console.print(f"[{style.get(role, 'dim')}]{label.get(role, role)}[/]: {content}")


def _show_sessions(store: MemoryStore, current_sid: str) -> None:
    sessions = store.list_sessions()
    if not sessions:
        console.print("[dim]（还没有任何会话）[/dim]")
        return
    for s in sessions:
        last = datetime.fromtimestamp(s["last"]).strftime("%m-%d %H:%M")
        mark = " [cyan]← 当前[/cyan]" if s["session_id"] == current_sid else ""
        console.print(f"  {s['session_id']}  ({s['n']} 条消息, 最后活跃 {last}){mark}")


def _show_memories(store: MemoryStore) -> None:
    memories = store.list_memories()
    if not memories:
        console.print("[dim]（还没有长期记忆）[/dim]")
        return
    for m in memories:
        day = datetime.fromtimestamp(m["created_at"]).strftime("%m-%d")
        tag = f" [{m['tags']}]" if m["tags"] else ""
        console.print(f"  #{m['id']} ({day}){tag} {m['content']}")


def _show_tools(agent: Agent) -> None:
    """列出所有已注册的 Function Call 工具。"""
    from minispark.tools.base import FunctionTool

    fc_tools = [t for t in agent.registry.tools if isinstance(t, FunctionTool)]
    if not fc_tools:
        console.print("[dim]（没有注册任何 Function Call 工具）[/dim]")
        return
    console.print(f"[bold]已注册 Function Call 工具 ({len(fc_tools)} 个):[/bold]")
    for t in fc_tools:
        desc = t.description.splitlines()[0] if t.description else "-"
        console.print(f"  [cyan]{t.name}[/cyan]  {desc}")


def _show_skills(agent: Agent) -> None:
    """列出所有已发现的技能。"""
    if not agent.skills:
        console.print("[dim]（没有发现任何技能）[/dim]")
        return
    console.print(f"[bold]已发现技能 ({len(agent.skills)} 个):[/bold]")
    for name, skill in agent.skills.items():
        desc = skill.description or "-"
        console.print(f"  [cyan]{name}[/cyan]  {desc}")


def _show_scheduler_status(agent: Agent) -> None:
    """显示调度器状态与任务列表。"""
    if agent.scheduler is None:
        console.print("[red]调度器未初始化[/red]")
        return
    s = agent.scheduler
    running = "✅ 运行中" if s.running else "❌ 未启动"
    console.print(f"[bold]调度器状态:[/bold] {running}")
    tasks = s.list()
    if not tasks:
        console.print("[dim]（没有定时任务）[/dim]")
        return
    console.print(f"[bold]定时任务 ({len(tasks)} 个):[/bold]")
    for t in tasks:
        status = "启用" if t.enabled else "停用"
        if t.run_at:
            schedule = f"定时 {t.run_at}（一次性）"
        elif t.cron_expression:
            schedule = f"cron: {t.cron_expression}"
        else:
            schedule = "无效"
        console.print(f"  [{status}] [cyan]{t.name}[/cyan] (ID: {t.id}) {schedule}")


async def _handle_slash(
    text: str,
    session: Session,
    store: MemoryStore | None,
    agent: Agent | None = None,
    email_channel: Any = None,
) -> Session:
    """处理斜杠命令，返回（可能已切换的）会话。"""
    from minispark.core.session import Session as _Session

    parts = text.split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd == "/tools_list":
        if agent is None:
            console.print("[red]Agent 未就绪[/red]")
            return session
        _show_tools(agent)
        return session
    if cmd == "/skills_list":
        if agent is None:
            console.print("[red]Agent 未就绪[/red]")
            return session
        _show_skills(agent)
        return session
    if cmd == "/cron_list":
        if agent is None:
            console.print("[red]Agent 未就绪[/red]")
            return session
        _show_scheduler_status(agent)
        return session
    if cmd == "/cron_cancel":
        if agent is None or agent.scheduler is None:
            console.print("[red]调度器未就绪[/red]")
            return session
        if not arg:
            console.print("[red]用法：/cron_cancel <任务ID>（ID 用 /cron_list 查看）[/red]")
            return session
        if agent.scheduler.remove(arg):
            console.print(f"[dim]已取消定时任务 (ID: {arg})[/dim]")
        else:
            console.print(f"[red]未找到定时任务 (ID: {arg})[/red]")
        return session
    if cmd == "/model":
        if agent is None:
            console.print("[red]Agent 未就绪[/red]")
            return session
        if arg:
            old = agent.model
            agent.switch_model(arg)
            console.print(f"[dim]模型已切换：{old} → [bold cyan]{agent.model}[/bold cyan][/dim]")
        else:
            console.print(f"[bold]当前模型:[/bold] [cyan underline]{agent.model}[/cyan underline]")
            with console.status("正在获取可用模型列表...", spinner="dots"):
                models = await agent.list_models()
            if models:
                console.print("[bold]可用模型:[/bold]")
                for m in models:
                    mark = " [cyan]← 当前[/cyan]" if m == agent.model else ""
                    console.print(f"  {m}{mark}")
            else:
                console.print("[dim]（未能获取模型列表）[/dim]")
        return session
    if cmd == "/help":
        console.print(_SLASH_HELP)
        return session
    if cmd == "/gmail_verification":
        if email_channel is None:
            console.print("[red]邮件通道未启用，请在 config.toml 中设置 [channels.email] enabled = true[/red]")
            return session
        console.print("[dim]正在打开浏览器进行 Gmail 授权...[/dim]")
        result = email_channel.verify()
        if "成功" in result:
            console.print(f"[green]{result}[/green]")
        else:
            console.print(f"[red]{result}[/red]")
        return session
    if cmd == "/history":
        limit = int(arg) if arg.isdigit() else 10
        _show_history(session, limit)
        return session
    if cmd == "/compact":
        if agent is None:
            console.print("[red]Agent 未就绪，无法压缩[/red]")
            return session
        before = len(session.messages)
        if before == 0:
            console.print("[dim]当前会话为空，无需压缩[/dim]")
            return session
        with console.status("正在压缩上下文...", spinner="dots"):
            did = await agent.compact(session, force=True)
        if did:
            console.print(
                f"[dim]已压缩上下文：{before} 条 → {len(session.messages)} 条"
                f"（旧消息已摘要化并归档）[/dim]"
            )
        else:
            console.print("[dim]消息过少，没有可压缩的旧切片[/dim]")
        return session
    if cmd == "/new":
        sid = arg or f"cli-{datetime.now():%m%d-%H%M}"
        console.print(f"[dim]已开新会话 [bold]{sid}[/bold]（长期记忆仍然保留）[/dim]")
        return _Session.new(sid, store=store)

    # 以下命令需要持久化存储
    if store is None:
        console.print("[red]记忆存储未启用，会话管理不可用[/red]")
        return session
    if cmd == "/sessions":
        _show_sessions(store, session.session_id)
        return session
    if cmd == "/memory":
        _show_memories(store)
        return session
    if cmd == "/forget":
        if not arg.isdigit():
            console.print("[red]用法：/forget <记忆编号>（编号用 /memory 查看）[/red]")
            return session
        if not Confirm.ask(f"确认删除记忆 #{arg}？", default=False):
            return session
        if store.delete_memory(int(arg)):
            console.print(f"[dim]已删除记忆 #{arg}[/dim]")
        else:
            console.print(f"[red]记忆 #{arg} 不存在[/red]")
        return session
    if cmd == "/load":
        if not arg:
            console.print("[red]用法：/load <会话名称>[/red]")
            return session
        known = {s["session_id"] for s in store.list_sessions()}
        if arg not in known:
            console.print(f"[red]会话 {arg} 不存在，用 /sessions 查看[/red]")
            return session
        console.print(f"[dim]已切换到会话 [bold]{arg}[/bold][/dim]")
        return _Session.new(arg, store=store)
    if cmd == "/delete":
        if not arg:
            console.print("[red]用法：/delete <会话名称>[/red]")
            return session
        if not Confirm.ask(f"确认删除会话 {arg} 的全部历史？", default=False):
            return session
        n = store.delete_session(arg)
        console.print(f"[dim]已删除 {arg}（{n} 条消息）[/dim]")
        if arg == session.session_id:
            return _Session.new(arg, store=store)  # 删的是当前会话：重置为空
        return session

    console.print("[dim]未知命令，输入 /help 查看会话命令[/dim]")
    return session


async def run_cli_channel(config: Config, config_path: Path) -> None:
    """启动终端对话通道。"""
    from minispark.channels.email import EmailChannel
    from minispark.core.agent import Agent
    from minispark.core.session import Session

    logger = logging.getLogger("minispark")

    if not config.provider.api_key:
        console.print(f"[red]未找到 API Key：请在 {config_path} 的 [provider] 中设置 api_key[/red]")
        raise SystemExit(1)

    agent = Agent.from_config_object(config, confirm=confirm_shell)
    session = Session.new("cli", store=agent.store)  # 落盘会话，重开自动恢复

    email_channel: EmailChannel | None = None
    if config.channels.email.enabled and config.channels.email.sender and config.channels.email.password:
        email_channel = EmailChannel(
            sender=config.channels.email.sender,
            password=config.channels.email.password,
            to=config.channels.email.to,
        )
        logger.debug("邮件通道已启用: %s -> %s", config.channels.email.sender, config.channels.email.to or "（未设置默认收件人）")
        from minispark.tools.function_call.email import create_email_tools
        for tool in create_email_tools(email_channel, default_to=config.channels.email.to):
            agent.registry.register(tool)

    if agent.scheduler:
        def _on_task_result(task, result: str) -> None:
            """定时任务触发后的回调：终端打印。"""
            console.print()
            console.print(
                Panel(
                    Markdown(result),
                    title=f"⏰ 定时任务「{task.name}」",
                    border_style="yellow",
                )
            )
            console.print("[bold green]你[/bold green] ", end="")

        agent.scheduler._on_result = _on_task_result

        async def _scheduled_run(prompt: str) -> str:
            root = logging.getLogger()
            saved = [(h, h.level) for h in root.handlers]
            try:
                for h, _ in saved:
                    h.setLevel(logging.WARNING)
                return await agent.run(prompt, session)
            finally:
                for h, orig in saved:
                    h.setLevel(orig)

        agent.scheduler.bind_agent(_scheduled_run)
        agent.scheduler.start()
        if agent.scheduler.running:
            logger.debug("调度器已启动，状态: 运行中")
        else:
            logger.error("调度器启动失败！状态: 未运行")

    _print_banner(config, agent, email_channel)

    while True:
        try:
            user_input = await asyncio.to_thread(Prompt.ask, "[bold green]你[/bold green]")
        except (EOFError, KeyboardInterrupt):
            break
        text = user_input.strip()
        if not text:
            continue
        if text.lower() in {"exit", "quit", ":q"}:
            break
        if text.startswith("/"):
            session = await _handle_slash(text, session, agent.store, agent=agent, email_channel=email_channel)
            continue
        try:
            reply = await _run_with_status(agent, text, session)
        except KeyboardInterrupt:
            console.print("[dim]已打断本轮对话[/dim]")
            continue
        except Exception as exc:
            console.print(f"[red]请求失败：{type(exc).__name__}: {exc}[/red]")
            continue
        console.print("[bold blue]MiniSpark[/bold blue]:", end=" ")
        console.print(Markdown(reply), soft_wrap=True)
    console.print("[dim]再见。[/dim]")