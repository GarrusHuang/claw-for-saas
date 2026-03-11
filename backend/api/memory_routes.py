"""
Memory 统计 API — 聚合三层 Memory 系统的统计数据。

供 Dashboard 展示"AI 越用越聪明"。
"""
from __future__ import annotations

from fastapi import APIRouter

from dependencies import (
    get_session_manager,
    get_correction_memory,
    get_learning_memory,
)

router = APIRouter(tags=["memory"])


@router.get("/api/memory/stats")
async def get_memory_stats():
    """
    聚合 Memory 系统全局统计。

    返回:
    - sessions: 会话数 + 用户数
    - corrections: 修正记录统计
    - learning: 学习经验统计
    """
    sm = get_session_manager()
    # 扫描所有用户目录获取全局统计
    session_count = 0
    user_count = 0
    if sm.base_dir.exists():
        user_dirs = [d for d in sm.base_dir.iterdir() if d.is_dir()]
        user_count = len(user_dirs)
        for user_dir in user_dirs:
            session_count += len(list(user_dir.glob("*.jsonl")))

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
