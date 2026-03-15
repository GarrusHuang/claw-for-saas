"""
EventBus → WebSocket Bridge.

订阅 EventBus 事件流，通过 NotificationManager 转发到用户的 WebSocket 连接。
替代原来的 SSE 流，EventBus 本身不需要任何改动。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from core.event_bus import EventBus

logger = logging.getLogger(__name__)


class EventBusWSBridge:
    """订阅 EventBus，转发事件到用户 WebSocket。"""

    def __init__(
        self,
        bus: EventBus,
        session_id: str,
        user_id: str,
        notification_manager: Any,
    ) -> None:
        self.bus = bus
        self.session_id = session_id
        self.user_id = user_id
        self.nm = notification_manager
        self._task: asyncio.Task | None = None

    async def run(self) -> None:
        """消费 EventBus 事件并转发到 WebSocket。"""
        try:
            async for event in self.bus.subscribe():
                event_type = event.get("event", "message")
                data = event.get("data", {})
                await self.nm.notify_user(self.user_id, "pipeline_event", {
                    "session_id": self.session_id,
                    "event_type": event_type,
                    "data": data,
                })
        except asyncio.CancelledError:
            logger.debug(f"WSBridge cancelled for session {self.session_id}")
        except Exception as e:
            logger.warning(f"WSBridge error for session {self.session_id}: {e}")

    def start(self) -> asyncio.Task:
        """启动 bridge 作为后台 asyncio task。"""
        self._task = asyncio.create_task(self.run())
        return self._task

    def stop(self) -> None:
        """停止 bridge。"""
        if self._task and not self._task.done():
            self._task.cancel()
