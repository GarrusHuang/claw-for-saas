"""
WebSocket 通知端点 — 全局推送通道。

客户端连接后持续接收服务端推送的事件 (定时任务完成、系统通知等)。
支持心跳保活和 JWT 认证。
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from dependencies import get_notification_manager

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/api/ws/notifications")
async def ws_notifications(
    ws: WebSocket,
    token: str = Query(default=""),
):
    """
    WebSocket 通知通道。

    连接时通过 query param `token` 传 JWT，验证用户身份。
    连接后服务端推送事件，客户端只需监听。
    """
    # 必须先 accept，否则 CORSMiddleware 会直接 403
    await ws.accept()

    # ── 认证 ──
    from config import settings
    user_id = "U001"
    if settings.auth_enabled:
        if not token:
            await ws.close(code=4001, reason="Missing token")
            return
        import jwt as pyjwt
        try:
            payload = pyjwt.decode(token, settings.auth_jwt_secret, algorithms=[settings.auth_jwt_algorithm])
            user_id = payload.get("sub", "anonymous")
        except Exception:
            await ws.close(code=4001, reason="Invalid token")
            return

    # ── 注册连接 ──
    manager = get_notification_manager()
    # connect() 内部不再调 accept()，因为已经 accept 了
    if user_id not in manager._connections:
        manager._connections[user_id] = set()
    manager._connections[user_id].add(ws)
    logger.info(f"WebSocket connected: user={user_id}, total={manager.connection_count}")

    try:
        while True:
            try:
                msg = await asyncio.wait_for(ws.receive_text(), timeout=60)
                if msg == "ping":
                    await ws.send_text('{"type":"pong"}')
            except asyncio.TimeoutError:
                try:
                    await ws.send_text('{"type":"ping"}')
                except Exception:
                    break
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug(f"WebSocket error for user={user_id}: {e}")
    finally:
        manager.disconnect(user_id, ws)
