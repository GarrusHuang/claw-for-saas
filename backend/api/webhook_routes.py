"""
A9: Webhook API — 注册/查看/删除/测试 Webhook 回调。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.auth import AuthUser, get_current_user
from dependencies import get_webhook_store, get_webhook_dispatcher

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


class WebhookRegisterRequest(BaseModel):
    url: str
    secret: str = ""
    events: list[str] = ["task_completed", "task_failed"]
    enabled: bool = True


@router.get("")
async def get_webhook(user: AuthUser = Depends(get_current_user)):
    """查看租户的 Webhook 配置。"""
    store = get_webhook_store()
    config = store.get(user.tenant_id)
    if not config:
        return {"config": None}
    return {"config": config.to_dict()}


@router.post("")
async def register_webhook(req: WebhookRegisterRequest, user: AuthUser = Depends(get_current_user)):
    """注册或更新 Webhook。"""
    from urllib.parse import urlparse
    parsed = urlparse(req.url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="Webhook URL must use http or https scheme")
    from agent.security_hooks import _is_unsafe_url
    if _is_unsafe_url(req.url):
        raise HTTPException(status_code=400, detail="Webhook URL must not target private/local networks")
    from core.webhook import WebhookConfig
    config = WebhookConfig(
        url=req.url,
        secret=req.secret,
        events=req.events,
        enabled=req.enabled,
    )
    store = get_webhook_store()
    store.save(user.tenant_id, config)
    return {"status": "saved", "config": config.to_dict()}


@router.delete("")
async def delete_webhook(user: AuthUser = Depends(get_current_user)):
    """删除 Webhook 配置。"""
    store = get_webhook_store()
    ok = store.delete(user.tenant_id)
    if not ok:
        raise HTTPException(status_code=404, detail="No webhook configured")
    return {"status": "deleted"}


@router.post("/test")
async def test_webhook(user: AuthUser = Depends(get_current_user)):
    """发送测试 Webhook。"""
    dispatcher = get_webhook_dispatcher()
    ok = await dispatcher.dispatch(
        tenant_id=user.tenant_id,
        event="test",
        data={"message": "This is a test webhook from Claw-for-SaaS"},
    )
    if ok:
        return {"status": "delivered"}
    return {"status": "failed", "detail": "Webhook delivery failed (check logs)"}
