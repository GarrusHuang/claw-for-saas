"""
SSE 响应助手。

将 EventBus 事件流转换为 sse_starlette 兼容格式。
sse_starlette.EventSourceResponse 期望 yield dict，
格式: {"event": "xxx", "data": "json_string"}

Phase 8 新增: 心跳机制 (15 秒无事件时发送 SSE comment)。
P1-C 新增: 客户端断开检测 — 关闭 EventBus 以触发 Runtime abort。
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator, Optional

from starlette.requests import Request

from core.event_bus import EventBus

logger = logging.getLogger(__name__)

# 心跳间隔 (秒)
HEARTBEAT_INTERVAL_S = 15

# 客户端断开检查间隔 (秒)
DISCONNECT_CHECK_INTERVAL_S = 2


async def event_bus_to_sse(
    bus: EventBus,
    request: Optional[Request] = None,
) -> AsyncIterator[dict]:
    """
    将 EventBus 事件流转换为 sse_starlette 兼容的 dict。

    sse_starlette 期望格式:
        {"event": "<event_type>", "data": "<json_string>"}
    它会自动格式化为 SSE 协议:
        event: <event_type>
        data: <json_string>

    包含心跳机制: 超过 HEARTBEAT_INTERVAL_S 秒无事件时
    发送 SSE comment (: heartbeat) 防止客户端断开。

    当 request 传入时，会周期性检查客户端是否已断开，
    断开后关闭 EventBus 以触发 Runtime abort。
    """
    # Start background disconnect checker if request is provided
    disconnect_task: Optional[asyncio.Task] = None
    if request is not None:
        async def _check_disconnect():
            try:
                while not bus.is_closed:
                    await asyncio.sleep(DISCONNECT_CHECK_INTERVAL_S)
                    if await request.is_disconnected():
                        logger.info(
                            "Client disconnected, closing EventBus",
                            extra={"trace_id": bus.trace_id},
                        )
                        bus.close()
                        break
            except asyncio.CancelledError:
                pass

        disconnect_task = asyncio.create_task(_check_disconnect())

    try:
        async for event in bus.subscribe():
            event_type = event.get("event", "message")
            data = json.dumps(event.get("data", {}), ensure_ascii=False)
            yield {"event": event_type, "data": data}
    finally:
        if disconnect_task is not None and not disconnect_task.done():
            disconnect_task.cancel()
            try:
                await disconnect_task
            except asyncio.CancelledError:
                pass


