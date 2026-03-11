"""
认证模块 — JWT + API Key 双模式认证。

auth_enabled=False (默认): 返回固定 dev 用户, 完全向后兼容。
auth_enabled=True:
  - jwt:     用户名密码登录 → Claw 签发 JWT
  - api_key: API Key + X-User-Id 头

用户/租户/API Key 数据存储在 SQLite 数据库中。
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)

# Optional bearer — allows requests without Authorization header (for auth_enabled=False)
_bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class AuthUser:
    """Authenticated user identity."""
    tenant_id: str = "default"
    user_id: str = "U001"
    roles: list[str] = field(default_factory=list)


# ── JWT helpers ──

def decode_jwt(token: str, secret: str, algorithm: str) -> dict:
    """Decode and verify a JWT token. Returns the payload dict."""
    try:
        payload = jwt.decode(token, secret, algorithms=[algorithm])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")


def issue_session_token(
    user_id: str,
    tenant_id: str,
    roles: list[str],
    secret: str,
    algorithm: str = "HS256",
    expires_in: int = 86400,
) -> str:
    """Sign a Claw session JWT."""
    now = int(time.time())
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "roles": roles,
        "iat": now,
        "exp": now + expires_in,
    }
    return jwt.encode(payload, secret, algorithm=algorithm)


# ── FastAPI dependency ──

async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> AuthUser:
    """
    FastAPI dependency — resolve current user from auth.

    - auth_enabled=False → dev default user
    - jwt → decode Bearer JWT
    - api_key → validate key via DB + read X-User-Id header
    """
    from config import settings

    if not settings.auth_enabled:
        return AuthUser(
            tenant_id=settings.auth_default_tenant_id,
            user_id=settings.auth_default_user_id,
        )

    # Auth is enabled — token is required
    if not credentials:
        raise HTTPException(status_code=401, detail="Authorization header required")

    token = credentials.credentials

    if settings.auth_mode == "api_key":
        from dependencies import get_database

        db = get_database()
        key_record = db.verify_api_key(token)
        if not key_record:
            raise HTTPException(status_code=401, detail="Invalid or expired API key")

        # API Key 关联到租户，user_id 从 header 获取
        user_id = request.headers.get("X-User-Id")
        if not user_id:
            raise HTTPException(status_code=400, detail="X-User-Id header required for API key auth")

        return AuthUser(tenant_id=key_record.tenant_id, user_id=user_id)

    # JWT mode — decode Bearer JWT
    if not settings.auth_jwt_secret:
        raise HTTPException(status_code=500, detail="JWT secret not configured")

    payload = decode_jwt(token, settings.auth_jwt_secret, settings.auth_jwt_algorithm)

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token missing 'sub' claim")

    tenant_id = payload.get("tenant_id", settings.auth_default_tenant_id)
    roles = payload.get("roles", [])

    return AuthUser(tenant_id=tenant_id, user_id=user_id, roles=roles)
