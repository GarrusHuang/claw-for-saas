"""
认证模块 — 四模式认证。

auth_enabled=False (默认): 返回固定 dev 用户, 完全向后兼容。
auth_enabled=True:
  - jwt:     嵌入模式, 宿主签发 JWT, Claw 验证
  - api_key: 嵌入模式, 宿主带 API Key + 头信息
  - oidc:    独立部署, OIDC 登录 → Claw 签发 session JWT
  - saml:    独立部署, SAML SSO → Claw 签发 session JWT

OIDC/SAML 模式下, 登录成功后 Claw 签发自己的 JWT (session token),
后续请求用此 token 验证, 走 JWT 同一条解码路径。
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
    """Sign a Claw session JWT after OIDC/SAML login."""
    now = int(time.time())
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "roles": roles,
        "iat": now,
        "exp": now + expires_in,
    }
    return jwt.encode(payload, secret, algorithm=algorithm)


# ── API Key helper ──

def verify_api_key(key: str, valid_keys: list[str]) -> bool:
    """Check if an API key is in the valid keys list."""
    return key in valid_keys


# ── OIDC helpers ──

_oidc_metadata_cache: dict | None = None


async def fetch_oidc_metadata(issuer: str) -> dict:
    """Fetch and cache OIDC discovery document."""
    global _oidc_metadata_cache
    if _oidc_metadata_cache is not None:
        return _oidc_metadata_cache

    import httpx

    discovery_url = f"{issuer.rstrip('/')}/.well-known/openid-configuration"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(discovery_url)
        resp.raise_for_status()
        _oidc_metadata_cache = resp.json()
        return _oidc_metadata_cache


def build_oidc_authorize_url(
    metadata: dict,
    client_id: str,
    redirect_uri: str,
    scopes: str,
    state: str,
) -> str:
    """Build OIDC authorization redirect URL."""
    from urllib.parse import urlencode

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scopes,
        "state": state,
    }
    return f"{metadata['authorization_endpoint']}?{urlencode(params)}"


async def exchange_oidc_code(
    metadata: dict,
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> dict:
    """Exchange authorization code for tokens."""
    import httpx

    token_endpoint = metadata["token_endpoint"]
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            token_endpoint,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
            },
        )
        resp.raise_for_status()
        return resp.json()


async def verify_oidc_id_token(
    id_token: str,
    metadata: dict,
    client_id: str,
) -> dict:
    """Verify OIDC id_token and return claims."""
    import httpx

    # Fetch JWKS
    jwks_uri = metadata["jwks_uri"]
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(jwks_uri)
        resp.raise_for_status()
        jwks = resp.json()

    from authlib.jose import JsonWebToken

    jws = JsonWebToken(["RS256", "ES256"])
    claims = jws.decode(id_token, jwks)
    claims.validate()

    # Verify audience
    if claims.get("aud") != client_id:
        raise HTTPException(status_code=401, detail="id_token audience mismatch")

    return dict(claims)


# ── SAML helpers ──

def prepare_saml_request(request: Request) -> dict:
    """Convert FastAPI Request to python3-saml request format."""
    return {
        "https": "on" if request.url.scheme == "https" else "off",
        "http_host": request.headers.get("host", "localhost"),
        "script_name": str(request.url.path),
        "get_data": dict(request.query_params),
        "post_data": {},
    }


# ── FastAPI dependency ──

async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> AuthUser:
    """
    FastAPI dependency — resolve current user from auth.

    - auth_enabled=False → dev default user
    - jwt / oidc / saml → decode Bearer JWT (Claw session token)
    - api_key → validate key + read X-Tenant-Id / X-User-Id headers
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
        valid_keys = [k.strip() for k in settings.auth_api_keys.split(",") if k.strip()]
        if not verify_api_key(token, valid_keys):
            raise HTTPException(status_code=401, detail="Invalid API key")

        tenant_id = request.headers.get("X-Tenant-Id", settings.auth_default_tenant_id)
        user_id = request.headers.get("X-User-Id")
        if not user_id:
            raise HTTPException(status_code=400, detail="X-User-Id header required for API key auth")

        return AuthUser(tenant_id=tenant_id, user_id=user_id)

    # JWT / OIDC / SAML — all use JWT verification for session tokens
    if not settings.auth_jwt_secret:
        raise HTTPException(status_code=500, detail="JWT secret not configured")

    payload = decode_jwt(token, settings.auth_jwt_secret, settings.auth_jwt_algorithm)

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token missing 'sub' claim")

    tenant_id = payload.get("tenant_id", settings.auth_default_tenant_id)
    roles = payload.get("roles", [])

    return AuthUser(tenant_id=tenant_id, user_id=user_id, roles=roles)
