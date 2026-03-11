"""
Hook Rule CRUD API 路由 — Phase 12。

端点:
- GET    /api/hook-rules          — 列出所有规则
- POST   /api/hook-rules          — 创建规则
- PUT    /api/hook-rules/{rule_id} — 更新规则
- DELETE /api/hook-rules/{rule_id} — 删除规则
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.auth import AuthUser, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/hook-rules", tags=["hook-rules"])


class HookRuleRequest(BaseModel):
    """Hook 规则创建/更新请求。"""
    rule_id: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=128)
    description: str = ""
    event_type: str = Field(default="pre_tool_use", pattern="^(pre_tool_use|post_tool_use|agent_stop|pre_compact)$")
    matcher: str | None = None
    condition: str = ""
    action: str = Field(default="block", pattern="^(block|modify|log)$")
    message_template: str = ""
    enabled: bool = True


def _get_engine():
    """获取 HookRuleEngine 实例。"""
    from dependencies import get_hook_rule_engine
    return get_hook_rule_engine()


@router.get("")
async def list_rules(_user: AuthUser = Depends(get_current_user)):
    """列出所有规则。"""
    engine = _get_engine()
    rules = engine.load_rules()
    return {"rules": [r.to_dict() for r in rules], "count": len(rules)}


@router.post("", status_code=201)
async def create_rule(req: HookRuleRequest, _user: AuthUser = Depends(get_current_user)):
    """创建新规则。"""
    from agent.hook_rules import HookRule

    engine = _get_engine()

    # 检查 rule_id 是否已存在
    existing = engine.get_rule(req.rule_id)
    if existing:
        raise HTTPException(status_code=409, detail=f"Rule {req.rule_id} already exists")

    rule = HookRule(
        rule_id=req.rule_id,
        name=req.name,
        description=req.description,
        event_type=req.event_type,
        matcher=req.matcher,
        condition=req.condition,
        action=req.action,
        message_template=req.message_template,
        enabled=req.enabled,
    )

    # 验证
    errors = engine.validate_rule(rule)
    if errors:
        raise HTTPException(status_code=400, detail={"errors": errors})

    engine.save_rule(rule)
    return {"rule_id": rule.rule_id, "status": "created"}


@router.put("/{rule_id}")
async def update_rule(rule_id: str, req: HookRuleRequest, _user: AuthUser = Depends(get_current_user)):
    """更新规则。"""
    from agent.hook_rules import HookRule

    engine = _get_engine()

    rule = HookRule(
        rule_id=rule_id,
        name=req.name,
        description=req.description,
        event_type=req.event_type,
        matcher=req.matcher,
        condition=req.condition,
        action=req.action,
        message_template=req.message_template,
        enabled=req.enabled,
    )

    errors = engine.validate_rule(rule)
    if errors:
        raise HTTPException(status_code=400, detail={"errors": errors})

    engine.save_rule(rule)
    return {"rule_id": rule_id, "status": "updated"}


@router.delete("/{rule_id}")
async def delete_rule(rule_id: str, _user: AuthUser = Depends(get_current_user)):
    """删除规则。"""
    engine = _get_engine()
    deleted = engine.delete_rule(rule_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Rule {rule_id} not found")
    return {"rule_id": rule_id, "status": "deleted"}
