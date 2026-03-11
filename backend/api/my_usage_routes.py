"""
自助用量查询 API (A10)。

前缀: /api/usage
任何已登录用户可访问（只看自己的数据）。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query

from core.auth import AuthUser, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/usage", tags=["my-usage"])


def _get_svc():
    from dependencies import get_usage_service
    return get_usage_service()


@router.get("/me")
async def get_my_usage(
    start_date: str | None = Query(None, description="YYYY-MM-DD"),
    end_date: str | None = Query(None, description="YYYY-MM-DD"),
    user: AuthUser = Depends(get_current_user),
):
    """我的汇总统计。"""
    return _get_svc().get_user_usage(user.tenant_id, user.user_id, start_date, end_date)


@router.get("/me/daily")
async def get_my_daily(
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    user: AuthUser = Depends(get_current_user),
):
    """我的日明细。"""
    return _get_svc().get_user_daily(user.tenant_id, user.user_id, start_date, end_date)


@router.get("/me/events")
async def get_my_events(
    limit: int = Query(50, ge=1, le=200),
    user: AuthUser = Depends(get_current_user),
):
    """我的最近事件。"""
    return _get_svc().get_recent_events(user.tenant_id, user.user_id, limit)
