"""
Session 管理路由 — 基于 SessionManager (JSONL 存储)。

端点:
- GET /api/session/list           — 列出当前用户的所有会话
- GET /api/session/{session_id}   — 获取会话历史
- DELETE /api/session/{session_id} — 删除会话
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from core.auth import AuthUser, get_current_user
from dependencies import get_session_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/session", tags=["session"])


@router.get("/list")
async def list_user_sessions(user: AuthUser = Depends(get_current_user)):
    """列出当前用户的所有会话。"""
    sm = get_session_manager()
    sessions = sm.list_sessions(user.tenant_id, user.user_id)
    return {"user_id": user.user_id, "sessions": sessions}


@router.get("/{session_id}")
async def get_session(session_id: str, user: AuthUser = Depends(get_current_user)):
    """获取指定会话的消息历史。"""
    sm = get_session_manager()
    if not sm.session_exists(user.tenant_id, user.user_id, session_id):
        return JSONResponse(
            status_code=404,
            content={"error": f"Session {session_id} not found"},
        )

    messages = sm.load_messages(user.tenant_id, user.user_id, session_id)
    return {
        "session_id": session_id,
        "user_id": user.user_id,
        "messages": messages,
        "message_count": len(messages),
    }


@router.delete("/{session_id}")
async def remove_session(session_id: str, user: AuthUser = Depends(get_current_user)):
    """删除指定会话。"""
    sm = get_session_manager()
    deleted = sm.delete_session(user.tenant_id, user.user_id, session_id)
    if not deleted:
        return JSONResponse(
            status_code=404,
            content={"error": f"Session {session_id} not found"},
        )
    return {"status": "deleted", "session_id": session_id, "user_id": user.user_id}
