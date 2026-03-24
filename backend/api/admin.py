"""
管理员 API — 租户、用户、API Key CRUD。

所有端点需要 admin 角色。
auth_enabled=False 时也可访问（dev 模式）。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.auth import AuthUser, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _require_admin(user: AuthUser) -> None:
    """检查管理员权限。dev 模式跳过。"""
    from config import settings
    if settings.auth_enabled and "admin" not in user.roles:
        raise HTTPException(status_code=403, detail="Admin role required")


# ── Tenant models ──

class CreateTenantRequest(BaseModel):
    tenant_id: str = Field(..., description="租户 ID")
    name: str = Field(..., description="租户名称")
    max_users: int = Field(100, description="最大用户数")


class UpdateTenantRequest(BaseModel):
    name: str | None = Field(None, description="租户名称")
    status: str | None = Field(None, description="状态: active | disabled")
    max_users: int | None = Field(None, description="最大用户数")


# ── User models ──

class CreateUserRequest(BaseModel):
    user_id: str = Field(..., description="用户 ID")
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")
    roles: list[str] = Field(default_factory=list, description="角色列表")


class UpdateUserRequest(BaseModel):
    password: str | None = Field(None, description="新密码")
    roles: list[str] | None = Field(None, description="角色列表")
    status: str | None = Field(None, description="状态: active | disabled")


# ── API Key models ──

class CreateApiKeyRequest(BaseModel):
    description: str = Field("", description="描述")
    expires_in_days: int | None = Field(None, description="过期天数 (空=永不过期)")


# ── Invite Code models ──

class CreateInviteCodeRequest(BaseModel):
    roles: list[str] = Field(default_factory=list, description="注册用户角色")
    max_uses: int = Field(1, description="最大使用次数")
    expires_in_days: int | None = Field(None, description="过期天数 (空=永不过期)")


# ═══════════════════════════════════════
# Tenant endpoints
# ═══════════════════════════════════════

@router.post("/tenants")
async def create_tenant(req: CreateTenantRequest, user: AuthUser = Depends(get_current_user)):
    """创建租户。"""
    _require_admin(user)
    from dependencies import get_database
    db = get_database()
    try:
        tenant = db.create_tenant(req.tenant_id, req.name, req.max_users)
        return {
            "tenant_id": tenant.tenant_id,
            "name": tenant.name,
            "status": tenant.status,
            "max_users": tenant.max_users,
        }
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/tenants")
async def list_tenants(user: AuthUser = Depends(get_current_user)):
    """列出所有租户。"""
    _require_admin(user)
    from dependencies import get_database
    db = get_database()
    tenants = db.list_tenants()
    return [
        {
            "tenant_id": t.tenant_id,
            "name": t.name,
            "status": t.status,
            "max_users": t.max_users,
        }
        for t in tenants
    ]


@router.get("/tenants/{tenant_id}")
async def get_tenant(tenant_id: str, user: AuthUser = Depends(get_current_user)):
    """获取租户详情。"""
    _require_admin(user)
    from dependencies import get_database
    db = get_database()
    tenant = db.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail=f"Tenant not found: {tenant_id}")
    return {
        "tenant_id": tenant.tenant_id,
        "name": tenant.name,
        "status": tenant.status,
        "max_users": tenant.max_users,
    }


@router.put("/tenants/{tenant_id}")
async def update_tenant(tenant_id: str, req: UpdateTenantRequest, user: AuthUser = Depends(get_current_user)):
    """更新租户。"""
    _require_admin(user)
    from dependencies import get_database
    db = get_database()
    ok = db.update_tenant(tenant_id, name=req.name, status=req.status, max_users=req.max_users)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Tenant not found: {tenant_id}")
    return {"ok": True}


@router.delete("/tenants/{tenant_id}")
async def delete_tenant(tenant_id: str, user: AuthUser = Depends(get_current_user)):
    """删除租户（级联删除用户和 API Key）。"""
    _require_admin(user)
    from dependencies import get_database
    db = get_database()
    ok = db.delete_tenant(tenant_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Tenant not found: {tenant_id}")
    return {"ok": True}


# ═══════════════════════════════════════
# User endpoints
# ═══════════════════════════════════════

@router.post("/tenants/{tenant_id}/users")
async def create_user(tenant_id: str, req: CreateUserRequest, user: AuthUser = Depends(get_current_user)):
    """在指定租户下创建用户。"""
    _require_admin(user)
    from dependencies import get_database
    db = get_database()

    # 检查租户存在
    if not db.get_tenant(tenant_id):
        raise HTTPException(status_code=404, detail=f"Tenant not found: {tenant_id}")

    try:
        u = db.create_user(tenant_id, req.user_id, req.username, req.password, req.roles)
        return {
            "user_id": u.user_id,
            "tenant_id": u.tenant_id,
            "username": u.username,
            "roles": u.roles,
            "status": u.status,
        }
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/tenants/{tenant_id}/users")
async def list_users(tenant_id: str, user: AuthUser = Depends(get_current_user)):
    """列出租户下所有用户。"""
    _require_admin(user)
    from dependencies import get_database
    db = get_database()
    users = db.list_users(tenant_id)
    return [
        {
            "user_id": u.user_id,
            "tenant_id": u.tenant_id,
            "username": u.username,
            "roles": u.roles,
            "status": u.status,
        }
        for u in users
    ]


@router.get("/tenants/{tenant_id}/users/{user_id}")
async def get_user(tenant_id: str, user_id: str, user: AuthUser = Depends(get_current_user)):
    """获取用户详情。"""
    _require_admin(user)
    from dependencies import get_database
    db = get_database()
    u = db.get_user(tenant_id, user_id)
    if not u:
        raise HTTPException(status_code=404, detail=f"User not found: {tenant_id}/{user_id}")
    return {
        "user_id": u.user_id,
        "tenant_id": u.tenant_id,
        "username": u.username,
        "roles": u.roles,
        "status": u.status,
    }


@router.put("/tenants/{tenant_id}/users/{user_id}")
async def update_user(
    tenant_id: str, user_id: str, req: UpdateUserRequest, user: AuthUser = Depends(get_current_user)
):
    """更新用户。"""
    _require_admin(user)
    from dependencies import get_database
    db = get_database()
    ok = db.update_user(tenant_id, user_id, password=req.password, roles=req.roles, status=req.status)
    if not ok:
        raise HTTPException(status_code=404, detail=f"User not found: {tenant_id}/{user_id}")
    return {"ok": True}


@router.delete("/tenants/{tenant_id}/users/{user_id}")
async def delete_user(tenant_id: str, user_id: str, user: AuthUser = Depends(get_current_user)):
    """删除用户。"""
    _require_admin(user)
    from dependencies import get_database
    db = get_database()
    ok = db.delete_user(tenant_id, user_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"User not found: {tenant_id}/{user_id}")
    return {"ok": True}


# ═══════════════════════════════════════
# API Key endpoints
# ═══════════════════════════════════════

@router.post("/tenants/{tenant_id}/api-keys")
async def create_api_key(tenant_id: str, req: CreateApiKeyRequest, user: AuthUser = Depends(get_current_user)):
    """创建 API Key。返回的 key 仅此时可见。"""
    _require_admin(user)
    from dependencies import get_database
    db = get_database()

    if not db.get_tenant(tenant_id):
        raise HTTPException(status_code=404, detail=f"Tenant not found: {tenant_id}")

    raw_key, record = db.create_api_key(tenant_id, req.description, req.expires_in_days)
    return {
        "key": raw_key,
        "key_id": record.key_id,
        "tenant_id": record.tenant_id,
        "description": record.description,
        "expires_at": record.expires_at,
        "warning": "Save this key now — it cannot be retrieved later.",
    }


@router.get("/tenants/{tenant_id}/api-keys")
async def list_api_keys(tenant_id: str, user: AuthUser = Depends(get_current_user)):
    """列出租户的所有 API Key（不含 key 值）。"""
    _require_admin(user)
    from dependencies import get_database
    db = get_database()
    keys = db.list_api_keys(tenant_id)
    return [
        {
            "key_id": k.key_id,
            "tenant_id": k.tenant_id,
            "description": k.description,
            "status": k.status,
            "created_at": k.created_at,
            "expires_at": k.expires_at,
        }
        for k in keys
    ]


@router.post("/tenants/{tenant_id}/api-keys/{key_id}/revoke")
async def revoke_api_key(tenant_id: str, key_id: str, user: AuthUser = Depends(get_current_user)):
    """撤销 API Key。"""
    _require_admin(user)
    from dependencies import get_database
    db = get_database()
    # Verify key belongs to this tenant
    keys = db.list_api_keys(tenant_id)
    if not any(k.key_id == key_id for k in keys):
        raise HTTPException(status_code=404, detail=f"API key not found: {key_id}")
    db.revoke_api_key(key_id)
    return {"ok": True}


@router.delete("/tenants/{tenant_id}/api-keys/{key_id}")
async def delete_api_key(tenant_id: str, key_id: str, user: AuthUser = Depends(get_current_user)):
    """删除 API Key。"""
    _require_admin(user)
    from dependencies import get_database
    db = get_database()
    # Verify key belongs to this tenant
    keys = db.list_api_keys(tenant_id)
    if not any(k.key_id == key_id for k in keys):
        raise HTTPException(status_code=404, detail=f"API key not found: {key_id}")
    db.delete_api_key(key_id)
    return {"ok": True}


# ═══════════════════════════════════════
# Invite Code endpoints (4.6)
# ═══════════════════════════════════════

@router.post("/tenants/{tenant_id}/invite-codes")
async def create_invite_code(
    tenant_id: str, req: CreateInviteCodeRequest, user: AuthUser = Depends(get_current_user),
):
    """生成邀请码。"""
    _require_admin(user)
    from dependencies import get_database
    import time

    db = get_database()
    if not db.get_tenant(tenant_id):
        raise HTTPException(status_code=404, detail=f"Tenant not found: {tenant_id}")

    expires_at = (time.time() + req.expires_in_days * 86400) if req.expires_in_days else None

    code = db.create_invite_code(
        tenant_id=tenant_id,
        roles=req.roles,
        max_uses=req.max_uses,
        expires_at=expires_at,
        created_by=user.user_id,
    )
    return {
        "code": code,
        "tenant_id": tenant_id,
        "roles": req.roles,
        "max_uses": req.max_uses,
        "expires_at": expires_at,
    }


@router.get("/tenants/{tenant_id}/invite-codes")
async def list_invite_codes(tenant_id: str, user: AuthUser = Depends(get_current_user)):
    """列出租户的所有邀请码。"""
    _require_admin(user)
    from dependencies import get_database
    db = get_database()
    codes = db.list_invite_codes(tenant_id)
    return [
        {
            "code": c.code,
            "tenant_id": c.tenant_id,
            "roles": c.roles,
            "max_uses": c.max_uses,
            "used_count": c.used_count,
            "expires_at": c.expires_at,
            "created_by": c.created_by,
            "created_at": c.created_at,
            "status": c.status,
        }
        for c in codes
    ]


@router.post("/tenants/{tenant_id}/invite-codes/{code}/revoke")
async def revoke_invite_code(
    tenant_id: str, code: str, user: AuthUser = Depends(get_current_user),
):
    """撤销邀请码。"""
    _require_admin(user)
    from dependencies import get_database
    db = get_database()
    # Verify code belongs to this tenant
    codes = db.list_invite_codes(tenant_id)
    if not any(c.code == code for c in codes):
        raise HTTPException(status_code=404, detail=f"Invite code not found: {code}")
    db.revoke_invite_code(code)
    return {"ok": True}


# ── #42/#29: Soul / Personality 租户级管理 ──

class SoulUpdateRequest(BaseModel):
    content: str = Field(..., description="Soul.md 内容")


@router.get("/tenant/{tenant_id}/soul")
async def get_tenant_soul(tenant_id: str, user: AuthUser = Depends(get_current_user)):
    """获取租户 Soul 覆盖内容。"""
    _require_admin(user)
    import os
    from pathlib import Path
    backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    soul_path = Path(backend_root) / "data" / "souls" / tenant_id / "soul.md"
    if not soul_path.exists():
        return {"tenant_id": tenant_id, "content": "", "exists": False}
    return {"tenant_id": tenant_id, "content": soul_path.read_text(encoding="utf-8"), "exists": True}


@router.put("/tenant/{tenant_id}/soul")
async def update_tenant_soul(tenant_id: str, req: SoulUpdateRequest, user: AuthUser = Depends(get_current_user)):
    """更新租户 Soul 覆盖。"""
    _require_admin(user)
    import os
    from pathlib import Path
    backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    soul_dir = Path(backend_root) / "data" / "souls" / tenant_id
    soul_dir.mkdir(parents=True, exist_ok=True)
    (soul_dir / "soul.md").write_text(req.content, encoding="utf-8")
    # 清除 PromptBuilder 缓存
    try:
        from dependencies import get_prompt_builder
        get_prompt_builder().invalidate_tenant_cache(tenant_id)
    except Exception:
        pass
    return {"ok": True, "tenant_id": tenant_id}


@router.get("/tenant/{tenant_id}/personality")
async def get_tenant_personality(tenant_id: str, user: AuthUser = Depends(get_current_user)):
    """获取租户 Personality 预设。"""
    _require_admin(user)
    import os
    from pathlib import Path
    backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = Path(backend_root) / "data" / "personalities" / f"{tenant_id}.md"
    if not path.exists():
        return {"tenant_id": tenant_id, "content": "", "exists": False}
    return {"tenant_id": tenant_id, "content": path.read_text(encoding="utf-8"), "exists": True}


@router.put("/tenant/{tenant_id}/personality")
async def update_tenant_personality(tenant_id: str, req: SoulUpdateRequest, user: AuthUser = Depends(get_current_user)):
    """更新租户 Personality 预设。"""
    _require_admin(user)
    import os
    from pathlib import Path
    backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pdir = Path(backend_root) / "data" / "personalities"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / f"{tenant_id}.md").write_text(req.content, encoding="utf-8")
    try:
        from dependencies import get_prompt_builder
        get_prompt_builder().invalidate_tenant_cache(tenant_id)
    except Exception:
        pass
    return {"ok": True, "tenant_id": tenant_id}
