"""
认证端点。

- POST /api/auth/login     — 用户名+密码登录 → JWT
- GET  /api/auth/me        — 返回当前用户
- POST /api/auth/refresh   — 刷新 token
- POST /api/auth/dev-token — 签发测试 JWT (仅 debug)
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.auth import AuthUser, get_current_user, issue_session_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    """用户登录请求。"""
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")
    tenant_id: str = Field("default", description="租户 ID")


class DevTokenRequest(BaseModel):
    """开发用 JWT 签发请求。"""
    user_id: str = Field("U001", description="User ID (sub claim)")
    tenant_id: str = Field("default", description="Tenant ID")
    roles: list[str] = Field(default_factory=list, description="Roles")
    expires_in: int = Field(3600, description="Token lifetime in seconds")


@router.post("/login")
async def login(req: LoginRequest):
    """用户名密码登录，返回 JWT token。"""
    from config import settings
    from dependencies import get_database

    if not settings.auth_enabled:
        raise HTTPException(status_code=400, detail="Auth is not enabled (dev mode uses default user)")

    if not settings.auth_jwt_secret:
        raise HTTPException(status_code=500, detail="JWT secret not configured")

    db = get_database()
    user = db.authenticate_user(req.tenant_id, req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = issue_session_token(
        user_id=user.user_id,
        tenant_id=user.tenant_id,
        roles=user.roles,
        secret=settings.auth_jwt_secret,
        algorithm=settings.auth_jwt_algorithm,
        expires_in=settings.auth_session_expire_s,
    )

    logger.info(f"Login success: tenant={user.tenant_id} user={user.user_id}")
    return {
        "token": token,
        "token_type": "bearer",
        "expires_in": settings.auth_session_expire_s,
        "user_id": user.user_id,
        "tenant_id": user.tenant_id,
    }


@router.get("/me")
async def get_me(user: AuthUser = Depends(get_current_user)):
    """返回当前认证用户信息。"""
    return {
        "tenant_id": user.tenant_id,
        "user_id": user.user_id,
        "roles": user.roles,
    }


@router.post("/refresh")
async def refresh_token(user: AuthUser = Depends(get_current_user)):
    """用当前有效 token 换发新 token (延长有效期)。"""
    from config import settings

    if not settings.auth_enabled:
        raise HTTPException(status_code=400, detail="Auth is not enabled")
    if not settings.auth_jwt_secret:
        raise HTTPException(status_code=500, detail="JWT secret not configured")

    token = issue_session_token(
        user_id=user.user_id,
        tenant_id=user.tenant_id,
        roles=user.roles,
        secret=settings.auth_jwt_secret,
        algorithm=settings.auth_jwt_algorithm,
        expires_in=settings.auth_session_expire_s,
    )
    return {"token": token, "token_type": "bearer", "expires_in": settings.auth_session_expire_s}


@router.post("/dev-token")
async def issue_dev_token(req: DevTokenRequest):
    """签发开发测试用 JWT。仅在 auth_enabled=True 且 app_debug=True 时可用。"""
    from config import settings

    if not settings.auth_enabled:
        raise HTTPException(status_code=400, detail="Auth is not enabled")
    if not settings.app_debug:
        raise HTTPException(status_code=403, detail="Dev token only available in debug mode")
    if not settings.auth_jwt_secret:
        raise HTTPException(status_code=500, detail="JWT secret not configured")

    token = issue_session_token(
        user_id=req.user_id,
        tenant_id=req.tenant_id,
        roles=req.roles,
        secret=settings.auth_jwt_secret,
        algorithm=settings.auth_jwt_algorithm,
        expires_in=req.expires_in,
    )
    return {"token": token, "token_type": "bearer", "expires_in": req.expires_in}
