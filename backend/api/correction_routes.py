"""
用户修正路由。

端点:
- POST /api/correction/submit — 提交用户修正
- GET /api/correction/preferences/{business_type} — 查询用户偏好
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core.auth import AuthUser, get_current_user
from dependencies import get_correction_memory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/correction", tags=["correction"])


class CorrectionSubmitRequest(BaseModel):
    """用户修正提交请求。"""
    business_type: str
    doc_type: str | None = None
    field_id: str
    agent_value: str
    user_value: str
    context_snapshot: dict[str, Any] = {}


@router.post("/submit")
async def submit_correction(
    req: CorrectionSubmitRequest,
    user: AuthUser = Depends(get_current_user),
):
    """
    提交用户修正。

    当用户编辑 Agent 填写的字段值后，前端调用此端点记录修正。
    修正将持久化到 CorrectionMemory，下次同类场景 Agent 会优先参考。
    """
    correction_memory = get_correction_memory()

    correction_memory.record_correction(
        user_id=user.user_id,
        business_type=req.business_type,
        doc_type=req.doc_type or "",
        field_id=req.field_id,
        agent_value=req.agent_value,
        user_value=req.user_value,
        context_snapshot=req.context_snapshot,
    )

    logger.info(
        f"Correction recorded: user={user.user_id}, field={req.field_id}, "
        f"{req.agent_value} → {req.user_value}"
    )

    return {
        "status": "recorded",
        "field_id": req.field_id,
        "message": f"修正已记录：{req.field_id} 从「{req.agent_value}」修正为「{req.user_value}」",
    }


@router.get("/preferences/{business_type}")
async def get_preferences(
    business_type: str,
    doc_type: str | None = None,
    user: AuthUser = Depends(get_current_user),
):
    """
    查询用户的历史修正偏好。

    返回该用户在指定业务类型下的所有修正记录，
    以及 build_preference_prompt 生成的偏好提示文本。
    """
    correction_memory = get_correction_memory()

    corrections = correction_memory.get_corrections(
        user_id=user.user_id,
        business_type=business_type,
        doc_type=doc_type,
    )

    # 构建偏好提示（与注入 Agent 的相同）
    field_ids = list(set(c.field_id for c in corrections))
    preference_prompt = correction_memory.build_preference_prompt(
        user_id=user.user_id,
        business_type=business_type,
        doc_type=doc_type or "",
        field_ids=field_ids,
    ) if field_ids else ""

    return {
        "user_id": user.user_id,
        "business_type": business_type,
        "correction_count": len(corrections),
        "corrections": [
            {
                "field_id": c.field_id,
                "agent_value": c.agent_value,
                "user_value": c.user_value,
                "times_applied": c.times_applied,
                "created_at": c.created_at,
            }
            for c in corrections
        ],
        "preference_prompt": preference_prompt,
    }
