"""QQ 机器人通道：腾讯官方 Bot API。

WebSocket 长连接收消息 + HTTP API 发消息，零额外进程。
"""

from __future__ import annotations

import asyncio
import json
import logging
import ssl

from pathlib import Path
from typing import Any

import certifi
import httpx
import websockets
from minispark.config import Config
from minispark.core.agent import Agent
from minispark.core.session import Session
from minispark.memory.store import MemoryStore
from minispark.scheduler import ScheduledTask
from minispark.tools.function_call.schedule import create_schedule_tools

logger = logging.getLogger("minispark.qq")

# ── 常量 ──────────────────────────────────────────────

SANDBOX_API = "https://sandbox.api.sgroup.qq.com"
FORMAL_API = "https://api.sgroup.qq.com"
AUTH_URL = "https://bots.qq.com/app/getAppAccessToken"

# WebSocket 操作码
OP_DISPATCH = 0
OP_HEARTBEAT = 1
OP_IDENTIFY = 2
OP_HELLO = 10
OP_HEARTBEAT_ACK = 11

# QQ Bot Intents
INTENT_GROUP_C2C = 1 << 25  # GROUP_AND_C2C_EVENT 群聊@ + 私聊消息

# ── SSL ────────────────────────────────────────────────


def _ssl_context() -> ssl.SSLContext:
    """用 certifi 证书包创建 SSL 上下文。

    不能用 ssl.create_default_context()：它会加载 Windows 系统证书库，
    库里若有损坏证书会在握手时抛 ASN1 解析错误。
    certifi 维护了自己的 CA bundle，httpx 默认用它，这里显式给 websockets 也用。
    """
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.load_verify_locations(cafile=certifi.where())
    return ctx


# ── 通道实现 ──────────────────────────────────────────


class QQBotChannel:
    """QQ 官方机器人通道。

    管理 WebSocket 长连接、Token 刷新、消息收发。
    """

    def __init__(
        self,
        app_id: str,
        secret: str,
        is_sandbox: bool = False,
        on_message: Any | None = None,
    ) -> None:
        self._app_id = app_id
        self._secret = secret
        self._is_sandbox = is_sandbox
        self._on_message = on_message
        self._api_base = SANDBOX_API if is_sandbox else FORMAL_API
        self._access_token: str | None = None
        self._token_expires: float = 0
        self._ws: Any = None
        self._seq: int = 0
        self._heartbeat_interval: int = 30
        self._running = False

    # ── Token 管理 ─────────────────────────────────

    async def _get_access_token(self) -> str:
        if self._access_token and asyncio.get_event_loop().time() < self._token_expires - 300:
            return self._access_token

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                AUTH_URL,
                json={"appId": self._app_id, "clientSecret": self._secret},
                headers={"Content-Type": "application/json"},
            )
            data = resp.json()
            if resp.status_code != 200:
                raise RuntimeError(f"获取 access_token 失败: {data}")

            self._access_token = data["access_token"]
            self._token_expires = asyncio.get_event_loop().time() + int(data.get("expires_in", 7200))
            logger.info("access_token 已更新，有效期 %s 秒", data.get("expires_in", 7200))
            return self._access_token

    # ── WebSocket 连接 ─────────────────────────────

    async def _get_ws_url(self) -> str:
        token = await self._get_access_token()
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._api_base}/gateway/bot",
                headers={"Authorization": f"QQBot {token}"},
            )
            data = resp.json()
            logger.info("网关响应 status=%s body=%s", resp.status_code, data)
            if resp.status_code != 200:
                raise RuntimeError(f"获取 WebSocket 地址失败: {data}")
            return data["url"]

    async def _connect_ws(self) -> None:
        ws_url = await self._get_ws_url()
        logger.info("正在连接 QQ WebSocket: %s", ws_url)

        self._ws = await websockets.connect(ws_url, ssl=_ssl_context())
        logger.info("QQ WebSocket 已连接")

        raw = await self._ws.recv()
        payload = json.loads(raw)
        if payload.get("op") == OP_HELLO:
            self._heartbeat_interval = payload["d"]["heartbeat_interval"] // 1000
            logger.info("收到 Hello，心跳间隔 %s 秒", self._heartbeat_interval)

        identify = {
            "op": OP_IDENTIFY,
            "d": {
                "token": f"QQBot {await self._get_access_token()}",
                "intents": INTENT_GROUP_C2C,
                "shard": [0, 1],
                "properties": {},
            },
        }
        await self._ws.send(json.dumps(identify))
        logger.info("已发送 Identify")

    # ── 消息收发 ───────────────────────────────────

    async def send_message(self, openid: str, content: str, reply_msg_id: str = "") -> bool:
        """发送私聊消息。
        
        :param openid: 用户 openid
        :param content: 消息内容
        :param reply_msg_id: 要回复的消息 ID（被动回复时必填）
        """
        token = await self._get_access_token()
        body: dict[str, object] = {"content": content, "msg_type": 0}
        if reply_msg_id:
            body["msg_id"] = reply_msg_id
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._api_base}/v2/users/{openid}/messages",
                json=body,
                headers={
                    "Authorization": f"QQBot {token}",
                    "Content-Type": "application/json",
                },
            )
            if resp.status_code == 200:
                return True
            logger.warning("发送消息失败 %s: %s", resp.status_code, resp.text)
            return False

    async def send_group_message(self, group_openid: str, content: str, reply_msg_id: str = "") -> bool:
        """发送群聊消息。
        
        :param group_openid: 群 openid
        :param content: 消息内容
        :param reply_msg_id: 要回复的消息 ID（被动回复时必填）
        """
        token = await self._get_access_token()
        body: dict[str, object] = {"content": content, "msg_type": 0}
        if reply_msg_id:
            body["msg_id"] = reply_msg_id
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._api_base}/v2/groups/{group_openid}/messages",
                json=body,
                headers={
                    "Authorization": f"QQBot {token}",
                    "Content-Type": "application/json",
                },
            )
            if resp.status_code == 200:
                return True
            logger.warning("发送群消息失败 %s: %s", resp.status_code, resp.text)
            return False

    # ── 主循环 ─────────────────────────────────────

    async def _heartbeat_loop(self) -> None:
        while self._running and self._ws:
            await asyncio.sleep(self._heartbeat_interval)
            if not self._ws:
                break
            try:
                await self._ws.send(json.dumps({"op": OP_HEARTBEAT, "d": self._seq}))
            except Exception:
                break

    async def _process_event(self, payload: dict[str, Any]) -> None:
        op = payload.get("op")
        if op == OP_DISPATCH:
            self._seq = payload.get("s", self._seq)
            event_type = payload.get("t", "")
            event_data = payload.get("d", {})

            if event_type == "C2C_MESSAGE_CREATE":
                author = event_data.get("author", {})
                openid = author.get("id", "")
                content = event_data.get("content", "").strip()
                msg_id = event_data.get("id", "")
                logger.info("私聊 %s: %s", openid, content[:50])

                if self._on_message:
                    await self._on_message("private", openid, content, msg_id)

            elif event_type == "GROUP_AT_MESSAGE_CREATE":
                group_openid = event_data.get("group_openid", "")
                author = event_data.get("author", {})
                openid = author.get("id", "")
                content = event_data.get("content", "").strip()
                msg_id = event_data.get("id", "")
                logger.info("群聊 %s/%s: %s", group_openid, openid, content[:50])

                if self._on_message:
                    await self._on_message("group", openid, content, msg_id, group_openid=group_openid)

        elif op == OP_HEARTBEAT_ACK:
            logger.debug("心跳 ACK Seq=%s", self._seq)

    async def run(self) -> None:
        """启动通道主循环（自动重连）。"""
        self._running = True
        while self._running:
            try:
                await self._connect_ws()
                heart_task = asyncio.create_task(self._heartbeat_loop())

                while self._running:
                    raw = await self._ws.recv()
                    payload = json.loads(raw)
                    await self._process_event(payload)

                heart_task.cancel()
            except websockets.ConnectionClosed as e:
                logger.warning("WebSocket 断开 code=%s reason=%s，5 秒后重连...", e.code, e.reason)
                await asyncio.sleep(5)
            except Exception as e:
                logger.error("QQ 通道异常: %s: %s，5 秒后重连...", type(e).__name__, e)
                await asyncio.sleep(5)
            finally:
                self._ws = None

    async def stop(self) -> None:
        """停止通道。"""
        self._running = False
        if self._ws:
            await self._ws.close()
            self._ws = None


# ── 启动入口 ──────────────────────────────────────────


async def run_qq_bot(config: Config, config_path: Path, *, daemon: bool = False) -> None:
    """启动 QQ 机器人通道。

    :param config: 全局配置对象
    :param config_path: 配置文件路径
    :param daemon: 是否为后台守护进程模式（--daemon 内部参数）
    """
    import signal as _signal

    qq_conf = config.channels.qq

    if not qq_conf.app_id or not qq_conf.secret:
        logger.error("QQ 通道未配置：请在 config.toml 的 [channels.qq] 中设置 app_id / secret")
        raise SystemExit(1)

    if not config.provider.api_key:
        logger.error("未找到 API Key：请在 %s 的 [provider] 中设置 api_key", config_path)
        raise SystemExit(1)

    agent = Agent.from_config_object(config)
    session = Session.new("qq", store=agent.store)

    if config.channels.email.enabled and config.channels.email.sender and config.channels.email.password:
        from minispark.channels.email import EmailChannel
        from minispark.tools.function_call.email import create_email_tools

        email_channel = EmailChannel(
            sender=config.channels.email.sender,
            password=config.channels.email.password,
            to=config.channels.email.to,
        )
        for tool in create_email_tools(email_channel, default_to=config.channels.email.to):
            agent.registry.register(tool)
        logger.debug("邮件工具已注册: %s -> %s", config.channels.email.sender, config.channels.email.to or "（未设置默认收件人）")

    if agent.scheduler:
        async def _scheduled_run(prompt: str) -> str:
            return await agent.run(prompt, session)

        agent.scheduler.bind_agent(_scheduled_run)
        agent.scheduler.start()

    channel = QQBotChannel(
        app_id=qq_conf.app_id,
        secret=qq_conf.secret,
        is_sandbox=qq_conf.is_sandbox,
    )

    channel._current_openid = ""
    channel._current_group_openid = ""
    channel._current_msg_type = ""

    if agent.scheduler:

        async def _on_schedule_result(task: ScheduledTask, result: str) -> None:
            logger.info("定时任务结果回调触发: %s, openid=%s, msg_type=%s",
                        task.name, task.openid, task.msg_type)
            if not task.openid:
                logger.warning("定时任务 %s 没有关联用户，结果无法推送", task.name)
                return
            try:
                if task.msg_type == "group" and task.group_openid:
                    ok = await channel.send_group_message(task.group_openid, result)
                else:
                    ok = await channel.send_message(task.openid, result)
                if ok:
                    logger.info("定时任务结果已推送: %s -> %s", task.name, task.openid)
                else:
                    logger.error("定时任务结果推送失败（API 返回非 200）: %s -> %s", task.name, task.openid)
            except Exception:
                logger.exception("定时任务结果推送异常: %s", task.name)

        agent.scheduler.set_on_result(_on_schedule_result)

        original_schedule = create_schedule_tools(agent.scheduler)
        for tool in original_schedule:
            if tool.name == "schedule_task":
                _orig_fn = tool.fn

                def _wrapped_schedule(
                    name: str,
                    run_at: str = "",
                    cron_expression: str = "",
                    prompt: str = "",
                    channel_name: str = "",
                    openid: str = "",
                    group_openid: str = "",
                    msg_type: str = "",
                    _fn=_orig_fn,
                ) -> str:
                    logger.info("schedule_task 被调用, openid=%s, group_openid=%s, msg_type=%s",
                                channel._current_openid, channel._current_group_openid, channel._current_msg_type)
                    return _fn(
                        name=name,
                        run_at=run_at,
                        cron_expression=cron_expression,
                        prompt=prompt,
                        channel=channel_name,
                        openid=channel._current_openid,
                        group_openid=channel._current_group_openid,
                        msg_type=channel._current_msg_type,
                    )

                from minispark.tools.base import FunctionTool
                wrapped_tool = FunctionTool(_wrapped_schedule, name="schedule_task")
                agent.registry.register(wrapped_tool)
                logger.debug("schedule_task 工具已包装（注入 openid）")

    _QQ_SLASH_HELP = """📋 会话命令
/new [名称]     开新会话（长期记忆保留，历史清零）
/sessions       列出所有会话
/load <名称>    切换到指定会话
/delete <名称>  删除指定会话的历史
/history        查看当前会话全部消息
/history -n N   查看当前会话最近 N 条消息
/compact        强制压缩当前会话上下文

📋 记忆命令
/memory         查看所有长期记忆
/forget <编号>  删除指定编号的长期记忆

📋 调试命令
/tools          列出所有已注册工具
/skills         列出所有已发现技能
/model [名称]   查看或切换模型
/cron           查看所有定时任务
/cron_cancel <ID>  取消指定定时任务

📋 其他
/help           显示本帮助"""


    async def _handle_qq_slash(
        text: str,
        session: Session,
        store: MemoryStore | None,
        agent: Agent,
    ) -> str:
        """处理 QQ 通道的斜杠命令，返回文本回复。"""
        from datetime import datetime

        parts = text.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        # ── 调试命令 ──
        if cmd == "/tools":
            from minispark.tools.base import FunctionTool
            fc_tools = [t for t in agent.registry.tools if isinstance(t, FunctionTool)]
            if not fc_tools:
                return "（没有注册任何工具）"
            lines = [f"已注册工具 ({len(fc_tools)} 个):"]
            for t in fc_tools:
                desc = t.description.splitlines()[0] if t.description else "-"
                lines.append(f"  {t.name}  {desc}")
            return "\n".join(lines)

        if cmd == "/skills":
            if not agent.skills:
                return "（没有发现任何技能）"
            lines = [f"已发现技能 ({len(agent.skills)} 个):"]
            for name, skill in agent.skills.items():
                lines.append(f"  {name}  {skill.description or '-'}")
            return "\n".join(lines)

        if cmd == "/cron":
            if agent.scheduler is None:
                return "调度器未初始化"
            s = agent.scheduler
            running = "运行中" if s.running else "未启动"
            tasks = s.list()
            if not tasks:
                return f"调度器状态: {running}\n（没有定时任务）"
            lines = [f"调度器状态: {running}", f"定时任务 ({len(tasks)} 个):"]
            for t in tasks:
                status = "启用" if t.enabled else "停用"
                if t.run_at:
                    schedule = f"定时 {t.run_at}（一次性）"
                elif t.cron_expression:
                    schedule = f"cron: {t.cron_expression}"
                else:
                    schedule = "无效"
                lines.append(f"  [{status}] {t.name} (ID: {t.id}) {schedule}")
            return "\n".join(lines)

        if cmd == "/cron_cancel":
            if agent.scheduler is None:
                return "调度器未就绪"
            if not arg:
                return "用法：/cron_cancel <任务ID>（ID 用 /cron 查看）"
            if agent.scheduler.remove(arg):
                return f"已取消定时任务 (ID: {arg})"
            return f"未找到定时任务 (ID: {arg})"

        if cmd == "/model":
            if arg:
                old = agent.model
                try:
                    agent.switch_model(arg)
                except Exception as e:
                    return f"模型切换失败: {e}"
                return f"模型已切换：{old} → {agent.model}"
            models = await agent.list_models()
            if not models:
                return f"当前模型: {agent.model}\n（未能获取模型列表）"
            lines = [f"当前模型: {agent.model}", "可用模型:"]
            for m in models:
                mark = " ← 当前" if m == agent.model else ""
                lines.append(f"  {m}{mark}")
            return "\n".join(lines)

        # ── 会话命令 ──
        if cmd == "/history":
            msgs = session.messages
            limit = 0
            if arg.startswith("-n ") and arg[3:].strip().isdigit():
                limit = int(arg[3:].strip())
            elif arg.isdigit():
                limit = int(arg)
            msgs = msgs[-limit:] if limit > 0 else msgs
            if not msgs:
                return "（当前会话暂无历史）"
            label = {"user": "你", "assistant": "MiniSpark", "tool": "工具"}
            lines = []
            for m in msgs:
                role = str(m.get("role"))
                content = str(m.get("content") or "")
                lines.append(f"[{label.get(role, role)}] {content}")
            return "\n".join(lines)

        if cmd == "/compact":
            if not agent:
                return "Agent 未就绪，无法压缩"
            before = len(session.messages)
            if before == 0:
                return "当前会话为空，无需压缩"
            did = await agent.compact(session, force=True)
            if did:
                return f"已压缩上下文：{before} 条 → {len(session.messages)} 条（旧消息已摘要化）"
            return "消息过少，没有可压缩的旧切片"

        if cmd == "/new":
            sid = arg or f"qq-{datetime.now():%m%d-%H%M}"
            new_session = Session.new(sid, store=store)
            session.messages = new_session.messages
            session.session_id = new_session.session_id
            session._persisted = new_session._persisted
            return f"已开新会话 {sid}（长期记忆仍然保留）"

        # ── 需要持久化存储的命令 ──
        if store is None:
            return "记忆存储未启用，会话管理不可用"

        if cmd == "/sessions":
            sessions = store.list_sessions()
            if not sessions:
                return "（还没有任何会话）"
            lines = []
            for s in sessions:
                last = datetime.fromtimestamp(s["last"]).strftime("%m-%d %H:%M")
                mark = " ← 当前" if s["session_id"] == session.session_id else ""
                lines.append(f"  {s['session_id']}  ({s['n']} 条消息, 最后活跃 {last}){mark}")
            return "\n".join(lines)

        if cmd == "/memory":
            memories = store.list_memories()
            if not memories:
                return "（还没有长期记忆）"
            lines = []
            for m in memories:
                day = datetime.fromtimestamp(m["created_at"]).strftime("%m-%d")
                tag = f" [{m['tags']}]" if m["tags"] else ""
                lines.append(f"  #{m['id']} ({day}){tag} {m['content']}")
            return "\n".join(lines)

        if cmd == "/forget":
            if not arg.isdigit():
                return "用法：/forget <记忆编号>（编号用 /memory 查看）"
            if store.delete_memory(int(arg)):
                return f"已删除记忆 #{arg}"
            return f"记忆 #{arg} 不存在"

        if cmd == "/load":
            if not arg:
                return "用法：/load <会话名称>"
            known = {s["session_id"] for s in store.list_sessions()}
            if arg not in known:
                return f"会话 {arg} 不存在，用 /sessions 查看"
            loaded = Session.new(arg, store=store)
            session.messages = loaded.messages
            session.session_id = loaded.session_id
            session._persisted = loaded._persisted
            return f"已切换到会话 {arg}"

        if cmd == "/delete":
            if not arg:
                return "用法：/delete <会话名称>"
            n = store.delete_session(arg)
            if arg == session.session_id:
                new_session = Session.new(arg, store=store)
                session.messages = new_session.messages
                session.session_id = new_session.session_id
                session._persisted = new_session._persisted
            return f"已删除 {arg}（{n} 条消息）"

        if cmd == "/help":
            return _QQ_SLASH_HELP

        return f"未知命令: {cmd}，输入 /help 查看帮助"


    async def on_message(
        msg_type: str,
        openid: str,
        content: str,
        msg_id: str,
        group_openid: str = "",
    ) -> None:
        if not content:
            return

        logger.info("QQ 收到消息 (%s): %s...", msg_type, content[:50])

        channel._current_openid = openid
        channel._current_group_openid = group_openid
        channel._current_msg_type = msg_type

        if content.startswith("/"):
            reply = await _handle_qq_slash(content, session, agent.store, agent)
        else:
            try:
                reply = await agent.run(content, session)
            except Exception as e:
                logger.exception("Agent 处理失败")
                reply = f"抱歉，处理出错了：{e}"

        if not reply:
            return

        ok = False
        if msg_type == "group" and group_openid:
            ok = await channel.send_group_message(group_openid, reply, reply_msg_id=msg_id)
        else:
            ok = await channel.send_message(openid, reply, reply_msg_id=msg_id)

        if ok:
            logger.info("QQ 回复已发送 (%s)", msg_type)
        else:
            logger.warning("QQ 回复发送失败 (%s)", msg_type)

    channel._on_message = on_message

    if daemon:
        def _shutdown(signum: int, frame: object) -> None:
            logger.info("收到信号 %s，正在关闭 QQ 机器人...", signum)
            channel._running = False

        _signal.signal(_signal.SIGTERM, _shutdown)
        _signal.signal(_signal.SIGINT, _shutdown)

    logger.info("QQ 机器人已启动 | App ID: %s | 环境: %s | API: %s",
                qq_conf.app_id,
                "沙箱（测试）" if qq_conf.is_sandbox else "正式",
                channel._api_base)

    try:
        await channel.run()
    except KeyboardInterrupt:
        logger.info("QQ 机器人已停止（KeyboardInterrupt）")
    except asyncio.CancelledError:
        logger.info("QQ 机器人任务已取消")
    finally:
        await channel.stop()
        logger.info("QQ 机器人已完全关闭")