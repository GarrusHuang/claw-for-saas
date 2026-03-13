"""
全局通知管理器 — WebSocket per-user 推送。

维护在线用户的 WebSocket 连接，支持向指定用户推送事件。
用于定时任务完成通知、系统消息等场景。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


@dataclass
class NotificationEvent:
    """通知事件。"""
    event_type: str
    data: dict
    timestamp: float = field(default_factory=time.time)

    def to_json(self) -> str:
        return json.dumps({
            "type": self.event_type,
            "data": self.data,
            "timestamp": self.timestamp,
        }, ensure_ascii=False)


class NotificationManager:
    """
    全局 WebSocket 通知管理器 (singleton)。

    每个用户可有多个连接 (多标签页)，按 user_id 分组。
    """

    def __init__(self) -> None:
        # user_id → set of WebSocket connections
        self._connections: dict[str, set[WebSocket]] = {}

    async def connect(self, user_id: str, ws: WebSocket) -> None:
        """注册用户的 WebSocket 连接 (调用方需先 ws.accept())。"""
        if user_id not in self._connections:
            self._connections[user_id] = set()
        self._connections[user_id].add(ws)
        logger.info(f"WebSocket connected: user={user_id}, total={self.connection_count}")

    def disconnect(self, user_id: str, ws: WebSocket) -> None:
        """移除用户的 WebSocket 连接。"""
        conns = self._connections.get(user_id)
        if conns:
            conns.discard(ws)
            if not conns:
                del self._connections[user_id]
        logger.info(f"WebSocket disconnected: user={user_id}, total={self.connection_count}")

    async def notify_user(self, user_id: str, event_type: str, data: dict | None = None) -> None:
        """向指定用户的所有连接推送通知。"""
        conns = self._connections.get(user_id)
        if not conns:
            return

        event = NotificationEvent(event_type=event_type, data=data or {})
        message = event.to_json()

        dead: list[WebSocket] = []
        for ws in conns:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)

        for ws in dead:
            conns.discard(ws)
        if not conns:
            self._connections.pop(user_id, None)

    async def broadcast(self, event_type: str, data: dict | None = None) -> None:
        """向所有在线用户推送通知。"""
        for user_id in list(self._connections):
            await self.notify_user(user_id, event_type, data)

    @property
    def connection_count(self) -> int:
        return sum(len(c) for c in self._connections.values())

    @property
    def online_users(self) -> list[str]:
        return list(self._connections.keys())
