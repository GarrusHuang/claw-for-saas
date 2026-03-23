"""
#27 Prompt Templates API — 用户级 Prompt 模板 CRUD。
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/templates", tags=["templates"])


def _get_store():
    from config import settings
    from core.prompt_templates import PromptTemplateStore
    return PromptTemplateStore(base_dir=settings.prompt_templates_dir)


def _get_user():
    """简化：从默认配置获取 tenant/user。生产环境用 auth 依赖。"""
    from config import settings
    return settings.auth_default_tenant_id, settings.auth_default_user_id


class SaveTemplateRequest(BaseModel):
    name: str
    content: str


@router.get("")
def list_templates():
    store = _get_store()
    tid, uid = _get_user()
    return {"templates": store.list_templates(tid, uid)}


@router.get("/{name}")
def get_template(name: str):
    store = _get_store()
    tid, uid = _get_user()
    t = store.get_template(tid, uid, name)
    if t is None:
        return {"error": f"模板 '{name}' 不存在"}
    return t


@router.post("")
def save_template(req: SaveTemplateRequest):
    store = _get_store()
    tid, uid = _get_user()
    return store.save_template(tid, uid, req.name, req.content)


@router.delete("/{name}")
def delete_template(name: str):
    store = _get_store()
    tid, uid = _get_user()
    if store.delete_template(tid, uid, name):
        return {"ok": True}
    return {"ok": False, "error": f"模板 '{name}' 不存在"}
