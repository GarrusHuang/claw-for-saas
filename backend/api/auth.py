"""
认证端点。

嵌入模式:
  - POST /api/auth/dev-token — 签发测试 JWT (仅 debug)
  - GET  /api/auth/me        — 返回当前用户

独立部署 (OIDC):
  - GET  /api/auth/login          — 重定向到 IdP 登录页
  - GET  /api/auth/callback/oidc  — OIDC 授权码回调 → 签发 Claw session token

独立部署 (SAML):
  - GET  /api/auth/login/saml          — 重定向到 SAML IdP
  - POST /api/auth/callback/saml       — SAML ACS 回调 → 签发 Claw session token

通用:
  - POST /api/auth/refresh  — 用未过期 token 换新 token
"""
from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from core.auth import (
    AuthUser,
    build_oidc_authorize_url,
    decode_jwt,
    exchange_oidc_code,
    fetch_oidc_metadata,
    get_current_user,
    issue_session_token,
    verify_oidc_id_token,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class DevTokenRequest(BaseModel):
    """开发用 JWT 签发请求。"""
    user_id: str = Field("U001", description="User ID (sub claim)")
    tenant_id: str = Field("default", description="Tenant ID")
    roles: list[str] = Field(default_factory=list, description="Roles")
    expires_in: int = Field(3600, description="Token lifetime in seconds")


@router.get("/me")
async def get_me(user: AuthUser = Depends(get_current_user)):
    """返回当前认证用户信息。"""
    return {
        "tenant_id": user.tenant_id,
        "user_id": user.user_id,
        "roles": user.roles,
    }


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


@router.get("/login")
async def oidc_login():
    """OIDC 登录入口 — 重定向到 IdP 登录页。仅 auth_mode=oidc 时可用。"""
    from config import settings

    if settings.auth_mode != "oidc":
        raise HTTPException(status_code=400, detail=f"Auth mode is '{settings.auth_mode}', not 'oidc'")
    if not settings.auth_oidc_issuer or not settings.auth_oidc_client_id:
        raise HTTPException(status_code=500, detail="OIDC not configured (missing issuer or client_id)")

    metadata = await fetch_oidc_metadata(settings.auth_oidc_issuer)
    state = secrets.token_urlsafe(32)

    authorize_url = build_oidc_authorize_url(
        metadata=metadata,
        client_id=settings.auth_oidc_client_id,
        redirect_uri=settings.auth_oidc_redirect_uri,
        scopes=settings.auth_oidc_scopes,
        state=state,
    )
    return RedirectResponse(url=authorize_url)


@router.get("/callback/oidc")
async def oidc_callback(code: str, state: str = ""):
    """OIDC 授权码回调 → 签发 Claw session token。"""
    from config import settings

    if settings.auth_mode != "oidc":
        raise HTTPException(status_code=400, detail="Auth mode is not 'oidc'")
    if not settings.auth_jwt_secret:
        raise HTTPException(status_code=500, detail="JWT secret not configured")

    metadata = await fetch_oidc_metadata(settings.auth_oidc_issuer)

    try:
        token_response = await exchange_oidc_code(
            metadata=metadata,
            code=code,
            client_id=settings.auth_oidc_client_id,
            client_secret=settings.auth_oidc_client_secret,
            redirect_uri=settings.auth_oidc_redirect_uri,
        )
    except Exception as e:
        logger.error(f"OIDC code exchange failed: {e}")
        raise HTTPException(status_code=401, detail=f"OIDC code exchange failed: {e}")

    id_token_raw = token_response.get("id_token")
    if not id_token_raw:
        raise HTTPException(status_code=401, detail="No id_token in response")

    try:
        claims = await verify_oidc_id_token(
            id_token=id_token_raw,
            metadata=metadata,
            client_id=settings.auth_oidc_client_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"OIDC id_token verification failed: {e}")
        raise HTTPException(status_code=401, detail=f"id_token verification failed: {e}")

    user_id = claims.get(settings.auth_oidc_user_claim)
    tenant_id = claims.get(settings.auth_oidc_tenant_claim, settings.auth_default_tenant_id)
    roles = claims.get("roles", [])
    if isinstance(roles, str):
        roles = [roles]

    if not user_id:
        raise HTTPException(status_code=401, detail=f"id_token missing '{settings.auth_oidc_user_claim}' claim")

    session_token = issue_session_token(
        user_id=str(user_id),
        tenant_id=str(tenant_id),
        roles=roles,
        secret=settings.auth_jwt_secret,
        algorithm=settings.auth_jwt_algorithm,
        expires_in=settings.auth_session_expire_s,
    )

    logger.info(f"OIDC login success: tenant={tenant_id} user={user_id}")
    return {
        "token": session_token,
        "token_type": "bearer",
        "expires_in": settings.auth_session_expire_s,
        "user_id": str(user_id),
        "tenant_id": str(tenant_id),
    }


@router.get("/login/saml")
async def saml_login(request: Request):
    """SAML 登录入口 — 重定向到 SAML IdP。仅 auth_mode=saml 时可用。"""
    from config import settings

    if settings.auth_mode != "saml":
        raise HTTPException(status_code=400, detail=f"Auth mode is '{settings.auth_mode}', not 'saml'")
    if not settings.auth_saml_idp_metadata_url:
        raise HTTPException(status_code=500, detail="SAML IdP metadata URL not configured")

    try:
        from onelogin.saml2.auth import OneLogin_Saml2_Auth
        from onelogin.saml2.idp_metadata_parser import OneLogin_Saml2_IdPMetadataParser
    except ImportError:
        raise HTTPException(status_code=500, detail="python3-saml not installed. Install with: pip install python3-saml")

    idp_data = OneLogin_Saml2_IdPMetadataParser.parse_remote(settings.auth_saml_idp_metadata_url)
    saml_settings = {
        "strict": True,
        "debug": settings.app_debug,
        "sp": {
            "entityId": settings.auth_saml_sp_entity_id,
            "assertionConsumerService": {
                "url": settings.auth_saml_sp_acs_url,
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
            },
        },
    }
    saml_settings.update(idp_data)

    from core.auth import prepare_saml_request
    req = prepare_saml_request(request)
    auth = OneLogin_Saml2_Auth(req, saml_settings)
    login_url = auth.login()
    return RedirectResponse(url=login_url)


@router.post("/callback/saml")
async def saml_callback(request: Request):
    """SAML ACS 回调 (POST binding) → 签发 Claw session token。"""
    from config import settings

    if settings.auth_mode != "saml":
        raise HTTPException(status_code=400, detail="Auth mode is not 'saml'")
    if not settings.auth_jwt_secret:
        raise HTTPException(status_code=500, detail="JWT secret not configured")

    try:
        from onelogin.saml2.auth import OneLogin_Saml2_Auth
        from onelogin.saml2.idp_metadata_parser import OneLogin_Saml2_IdPMetadataParser
    except ImportError:
        raise HTTPException(status_code=500, detail="python3-saml not installed")

    idp_data = OneLogin_Saml2_IdPMetadataParser.parse_remote(settings.auth_saml_idp_metadata_url)
    saml_settings = {
        "strict": True,
        "debug": settings.app_debug,
        "sp": {
            "entityId": settings.auth_saml_sp_entity_id,
            "assertionConsumerService": {
                "url": settings.auth_saml_sp_acs_url,
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
            },
        },
    }
    saml_settings.update(idp_data)

    form = await request.form()
    from core.auth import prepare_saml_request
    req = prepare_saml_request(request)
    req["post_data"] = dict(form)

    auth = OneLogin_Saml2_Auth(req, saml_settings)
    auth.process_response()

    errors = auth.get_errors()
    if errors:
        logger.error(f"SAML validation errors: {errors}")
        raise HTTPException(status_code=401, detail=f"SAML validation failed: {', '.join(errors)}")

    if not auth.is_authenticated():
        raise HTTPException(status_code=401, detail="SAML authentication failed")

    attrs = auth.get_attributes()
    name_id = auth.get_nameid()

    user_id = attrs.get(settings.auth_saml_user_attr, [name_id])[0] if attrs.get(settings.auth_saml_user_attr) else name_id
    tenant_id = attrs.get(settings.auth_saml_tenant_attr, [settings.auth_default_tenant_id])[0] if attrs.get(settings.auth_saml_tenant_attr) else settings.auth_default_tenant_id
    roles = attrs.get("roles", [])

    if not user_id:
        raise HTTPException(status_code=401, detail="SAML response missing user identity")

    session_token = issue_session_token(
        user_id=str(user_id),
        tenant_id=str(tenant_id),
        roles=roles,
        secret=settings.auth_jwt_secret,
        algorithm=settings.auth_jwt_algorithm,
        expires_in=settings.auth_session_expire_s,
    )

    logger.info(f"SAML login success: tenant={tenant_id} user={user_id}")
    return {
        "token": session_token,
        "token_type": "bearer",
        "expires_in": settings.auth_session_expire_s,
        "user_id": str(user_id),
        "tenant_id": str(tenant_id),
    }
