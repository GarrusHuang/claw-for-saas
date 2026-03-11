"""
Memory 统计 API — 聚合三层 Memory 系统的统计数据。

供 Dashboard 展示"AI 越用越聪明"。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from core.auth import AuthUser, get_current_user
from dependencies import (
    get_session_manager,
    get_correction_memory,
    get_learning_memory,
)

router = APIRouter(tags=["memory"])


@router.get("/api/memory/stats")
async def get_memory_stats(_user: AuthUser = Depends(get_current_user)):
    """
    聚合 Memory 系统全局统计。

    返回:
    - sessions: 会话数 + 用户数
    - corrections: 修正记录统计
    - learning: 学习经验统计
    """
    sm = get_session_manager()
    # 扫描所有 tenant/user 目录获取全局统计
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

    correction_stats = get_correction_memory().get_stats()
    learning_stats = get_learning_memory().get_stats()

    return {
        "sessions": {
            "count": session_count,
            "user_count": user_count,
        },
        "corrections": correction_stats,
        "learning": learning_stats,
    }
