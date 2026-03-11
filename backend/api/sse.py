"""
SSE 响应助手。

将 EventBus 事件流转换为 sse_starlette 兼容格式。
sse_starlette.EventSourceResponse 期望 yield dict，
格式: {"event": "xxx", "data": "json_string"}

Phase 8 新增: 心跳机制 (15 秒无事件时发送 SSE comment)。
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator

from core.event_bus import EventBus

logger = logging.getLogger(__name__)

# 心跳间隔 (秒)
HEARTBEAT_INTERVAL_S = 15


async def event_bus_to_sse(bus: EventBus) -> AsyncIterator[dict]:
    """
    将 EventBus 事件流转换为 sse_starlette 兼容的 dict。

    sse_starlette 期望格式:
        {"event": "<event_type>", "data": "<json_string>"}
    它会自动格式化为 SSE 协议:
        event: <event_type>
        data: <json_string>

    包含心跳机制: 超过 HEARTBEAT_INTERVAL_S 秒无事件时
    发送 SSE comment (: heartbeat) 防止客户端断开。
    """
    async for event in bus.subscribe():
        event_type = event.get("event", "message")
        data = json.dumps(event.get("data", {}), ensure_ascii=False)
        yield {"event": event_type, "data": data}


