"""
Session 管理路由 — 基于 SessionManager (JSONL 存储)。

端点:
- GET /api/session/{user_id}/list           — 列出用户的所有会话
- GET /api/session/{user_id}/{session_id}   — 获取会话历史
- DELETE /api/session/{user_id}/{session_id} — 删除会话
"""
from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from dependencies import get_session_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/session", tags=["session"])


@router.get("/{user_id}/list")
async def list_user_sessions(user_id: str):
    """列出用户的所有会话。"""
    sm = get_session_manager()
    sessions = sm.list_sessions(user_id)
    return {"user_id": user_id, "sessions": sessions}


@router.get("/{user_id}/{session_id}")
async def get_session(user_id: str, session_id: str):
    """获取指定会话的消息历史。"""
    sm = get_session_manager()
    if not sm.session_exists(user_id, session_id):
        return JSONResponse(
            status_code=404,
            content={"error": f"Session {session_id} not found for user {user_id}"},
        )

    messages = sm.load_messages(user_id, session_id)
    return {
        "session_id": session_id,
        "user_id": user_id,
        "messages": messages,
        "message_count": len(messages),
    }


@router.delete("/{user_id}/{session_id}")
async def remove_session(user_id: str, session_id: str):
    """删除指定会话。"""
    sm = get_session_manager()
    deleted = sm.delete_session(user_id, session_id)
    if not deleted:
        return JSONResponse(
            status_code=404,
            content={"error": f"Session {session_id} not found for user {user_id}"},
        )
    return {"status": "deleted", "session_id": session_id, "user_id": user_id}
