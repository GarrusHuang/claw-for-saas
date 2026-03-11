"""
Memory API (A8 重构) — Markdown 分层笔记 CRUD + 统计。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from core.auth import AuthUser, get_current_user
from dependencies import get_session_manager, get_memory_store

router = APIRouter(tags=["memory"])


@router.get("/api/memory/stats")
async def get_memory_stats(user: AuthUser = Depends(get_current_user)):
    """
    聚合 Memory 系统统计。

    返回:
    - sessions: 会话数 + 用户数
    - memory: Markdown 笔记文件统计
    """
    sm = get_session_manager()
    session_count = 0
    user_ids: set[str] = set()
    if sm.base_dir.exists():
        for tenant_dir in sm.base_dir.iterdir():
            if not tenant_dir.is_dir():
                continue
            for user_dir in tenant_dir.iterdir():
                if not user_dir.is_dir():
                    continue
                user_ids.add(user_dir.name)
                session_count += len(list(user_dir.glob("*.jsonl")))
    user_count = len(user_ids)

    store = get_memory_store()
    memory_stats = store.get_stats(
        tenant_id=user.tenant_id,
        user_id=user.user_id,
    )

    return {
        "sessions": {
            "count": session_count,
            "user_count": user_count,
        },
        "memory": memory_stats,
    }


@router.get("/api/memory/files")
async def list_memory_files(
    scope: str = "user",
    user: AuthUser = Depends(get_current_user),
):
    """列出指定层级的记忆文件。"""
    store = get_memory_store()
    files = store.list_files(
        scope=scope,
        tenant_id=user.tenant_id,
        user_id=user.user_id,
    )
    return {"scope": scope, "files": files}


@router.get("/api/memory/read")
async def read_memory_file(
    scope: str = "user",
    file: str = "",
    user: AuthUser = Depends(get_current_user),
):
    """读取指定记忆文件内容。"""
    store = get_memory_store()
    if file:
        content = store.read_file(
            scope=scope, filename=file,
            tenant_id=user.tenant_id, user_id=user.user_id,
        )
    else:
        content = store.read_all(
            scope=scope,
            tenant_id=user.tenant_id, user_id=user.user_id,
        )
    return {"scope": scope, "file": file, "content": content}
