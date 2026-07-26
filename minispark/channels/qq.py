"""QQ 机器人通道：腾讯官方 Bot API。

WebSocket 长连接收消息 + HTTP API 发消息，零额外进程。
"""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
import uuid
from pathlib import Path
from typing import Any

import certifi
import httpx
import websockets
from rich.console import Console

from minispark.config import Config
from minispark.core.agent import Agent
from minispark.core.session import Session

console = Console()
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

# QQ Bot Intents（按位或）
INTENT_C2C = 1 << 25       # C2C_MESSAGE_CREATE 私聊消息
INTENT_GROUP_AT = 1 << 25  # GROUP_AT_MESSAGE_CREATE 群聊@消息
INTENT_PUBLIC_GUILD = 1 << 0  # 频道公开消息

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
                "intents": INTENT_C2C | INTENT_GROUP_AT,
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
        msg_id = reply_msg_id if reply_msg_id else uuid.uuid4().hex
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._api_base}/v2/users/{openid}/messages",
                json={"content": content, "msg_type": 0, "msg_id": msg_id},
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
        msg_id = reply_msg_id if reply_msg_id else uuid.uuid4().hex
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._api_base}/v2/groups/{group_openid}/messages",
                json={"content": content, "msg_type": 0, "msg_id": msg_id},
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


async def run_qq_bot(config: Config, config_path: Path) -> None:
    """启动 QQ 机器人通道。"""
    qq_conf = config.channels.qq

    if not qq_conf.app_id or not qq_conf.secret:
        console.print("[red]QQ 通道未配置：请在 config.toml 的 [channels.qq] 中设置 app_id / secret[/red]")
        raise SystemExit(1)

    if not config.provider.api_key:
        console.print(f"[red]未找到 API Key：请在 {config_path} 的 [provider] 中设置 api_key[/red]")
        raise SystemExit(1)

    agent = Agent.from_config_object(config)
    session = Session.new("qq", store=agent.store)

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

    async def on_message(
        msg_type: str,
        openid: str,
        content: str,
        msg_id: str,
        group_openid: str = "",
    ) -> None:
        if not content:
            return

        console.print(f"[dim]QQ 收到消息 ({msg_type}): {content[:50]}...[/dim]")

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
            console.print(f"[dim]QQ 回复已发送 ({msg_type})[/dim]")
        else:
            console.print(f"[red]QQ 回复发送失败 ({msg_type})[/red]")

    channel._on_message = on_message

    console.print(f"[cyan]QQ 机器人已启动[/cyan]")
    console.print(f"  App ID: {qq_conf.app_id}")
    console.print(f"  环境: {'沙箱（测试）' if qq_conf.is_sandbox else '正式'}")
    console.print(f"  API: {channel._api_base}")

    try:
        await channel.run()
    except KeyboardInterrupt:
        console.print("[dim]QQ 机器人已停止[/dim]")
    finally:
        await channel.stop()