"""
管理员用量查询 API (A10)。

前缀: /api/admin/usage
所有端点需要 admin 角色。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from core.auth import AuthUser, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/usage", tags=["admin-usage"])


def _require_admin(user: AuthUser) -> None:
    from config import settings
    if settings.auth_enabled and "admin" not in user.roles:
        raise HTTPException(status_code=403, detail="Admin role required")


def _get_svc():
    from dependencies import get_usage_service
    return get_usage_service()


@router.get("/tenant/{tenant_id}")
async def get_tenant_usage(
    tenant_id: str,
    start_date: str | None = Query(None, description="YYYY-MM-DD"),
    end_date: str | None = Query(None, description="YYYY-MM-DD"),
    user: AuthUser = Depends(get_current_user),
):
    """租户汇总统计。"""
    _require_admin(user)
    return _get_svc().get_tenant_usage(tenant_id, start_date, end_date)


@router.get("/tenant/{tenant_id}/daily")
async def get_tenant_daily(
    tenant_id: str,
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    user: AuthUser = Depends(get_current_user),
):
    """租户日明细。"""
    _require_admin(user)
    return _get_svc().get_tenant_daily(tenant_id, start_date, end_date)


@router.get("/tenant/{tenant_id}/users")
async def get_tenant_user_ranking(
    tenant_id: str,
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    user: AuthUser = Depends(get_current_user),
):
    """用户排名。"""
    _require_admin(user)
    return _get_svc().get_tenant_user_ranking(tenant_id, start_date, end_date, limit)


@router.get("/tenant/{tenant_id}/users/{target_user_id}")
async def get_user_usage(
    tenant_id: str,
    target_user_id: str,
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    user: AuthUser = Depends(get_current_user),
):
    """单用户统计。"""
    _require_admin(user)
    return _get_svc().get_user_usage(tenant_id, target_user_id, start_date, end_date)


@router.get("/tenant/{tenant_id}/tools")
async def get_tool_usage_stats(
    tenant_id: str,
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    user: AuthUser = Depends(get_current_user),
):
    """工具使用频率。"""
    _require_admin(user)
    return _get_svc().get_tool_usage_stats(tenant_id, start_date, end_date)


@router.get("/tenant/{tenant_id}/events")
async def get_recent_events(
    tenant_id: str,
    user_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    user: AuthUser = Depends(get_current_user),
):
    """原始事件列表。"""
    _require_admin(user)
    return _get_svc().get_recent_events(tenant_id, user_id, limit)


@router.get("/tenant/{tenant_id}/storage")
async def get_storage_usage(
    tenant_id: str,
    user_id: str | None = Query(None),
    user: AuthUser = Depends(get_current_user),
):
    """存储用量。"""
    _require_admin(user)
    return _get_svc().get_storage_usage(tenant_id, user_id)
