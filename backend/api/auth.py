"""
认证端点。

- POST /api/auth/login     — 用户名+密码登录 → JWT
- POST /api/auth/register  — 邀请码注册
- GET  /api/auth/me        — 返回当前用户
- POST /api/auth/refresh   — 刷新 token
- POST /api/auth/dev-token — 签发测试 JWT (仅 debug)
"""
from __future__ import annotations

import logging
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from core.auth import AuthUser, get_current_user, issue_session_token

logger = logging.getLogger(__name__)

# ── 登录限速 (IP 级 + 账户级) ──
_login_attempts: dict[str, list[float]] = {}  # key → [timestamp, ...]
_LOGIN_WINDOW_S = 300  # 5 分钟窗口
_LOGIN_MAX_PER_IP = 20  # 每 IP 最多 20 次/5min
_LOGIN_MAX_PER_ACCOUNT = 5  # 每账户最多 5 次/5min


def _check_login_rate(key: str, max_attempts: int) -> bool:
    """检查限速，返回 True=允许，False=超限。"""
    now = time.time()
    cutoff = now - _LOGIN_WINDOW_S
    attempts = _login_attempts.get(key, [])
    attempts = [t for t in attempts if t > cutoff]
    _login_attempts[key] = attempts
    if len(attempts) >= max_attempts:
        return False
    attempts.append(now)
    return True

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
async def login(req: LoginRequest, request: Request):
    """用户名密码登录，返回 JWT token。"""
    from config import settings
    from dependencies import get_database

    if not settings.auth_enabled:
        raise HTTPException(status_code=400, detail="Auth is not enabled (dev mode uses default user)")

    if not settings.auth_jwt_secret:
        raise HTTPException(status_code=500, detail="JWT secret not configured")

    # 限速检查: IP 级
    client_ip = request.client.host if request.client else "unknown"
    if not _check_login_rate(f"ip:{client_ip}", _LOGIN_MAX_PER_IP):
        logger.warning(f"Login rate limit exceeded for IP {client_ip}")
        raise HTTPException(status_code=429, detail="Too many login attempts, please try again later")

    # 限速检查: 账户级
    account_key = f"acct:{req.tenant_id}:{req.username}"
    if not _check_login_rate(account_key, _LOGIN_MAX_PER_ACCOUNT):
        logger.warning(f"Login rate limit exceeded for account {req.username}")
        raise HTTPException(status_code=429, detail="Too many login attempts for this account, please try again later")

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

    logger.info(f"Login success: tenant={user.tenant_id}")
    return {
        "token": token,
        "token_type": "bearer",
        "expires_in": settings.auth_session_expire_s,
        "user_id": user.user_id,
        "tenant_id": user.tenant_id,
    }


class RegisterRequest(BaseModel):
    """用户注册请求 (邀请码制)。"""
    invite_code: str = Field(..., description="邀请码")
    username: str = Field(..., min_length=2, max_length=50, description="用户名")
    password: str = Field(..., min_length=6, max_length=128, description="密码")


# ── 注册限速 (IP 级) ──
_REGISTER_MAX_PER_IP = 5  # 每 IP 最多 5 次/5min


@router.post("/register")
async def register(req: RegisterRequest, request: Request):
    """邀请码注册，返回 JWT token。"""
    from config import settings
    from dependencies import get_database

    if not settings.auth_enabled:
        raise HTTPException(status_code=403, detail="Registration requires auth to be enabled")

    if not settings.auth_jwt_secret:
        raise HTTPException(status_code=500, detail="JWT secret not configured")

    # 限速检查: IP 级
    client_ip = request.client.host if request.client else "unknown"
    if not _check_login_rate(f"reg_ip:{client_ip}", _REGISTER_MAX_PER_IP):
        logger.warning(f"Register rate limit exceeded for IP {client_ip}")
        raise HTTPException(status_code=429, detail="Too many registration attempts, please try again later")

    db = get_database()

    # 消费邀请码
    result = db.consume_invite_code(req.invite_code)
    if result is None:
        raise HTTPException(status_code=400, detail="Invalid, expired, or exhausted invite code")

    tenant_id, roles = result
    user_id = f"U{secrets.token_hex(4).upper()}"

    # 创建用户
    try:
        user = db.create_user(
            tenant_id=tenant_id,
            user_id=user_id,
            username=req.username,
            password=req.password,
            roles=roles,
        )
    except ValueError as e:
        if "already exists" in str(e).lower() or "username" in str(e).lower():
            raise HTTPException(status_code=409, detail=f"Username already exists: {req.username}")
        raise HTTPException(status_code=400, detail=str(e))

    # 签发 JWT
    token = issue_session_token(
        user_id=user.user_id,
        tenant_id=user.tenant_id,
        roles=user.roles,
        secret=settings.auth_jwt_secret,
        algorithm=settings.auth_jwt_algorithm,
        expires_in=settings.auth_session_expire_s,
    )

    logger.info(f"Registration success: tenant={user.tenant_id}, user={user.user_id}")
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
