"""
用户修正路由 (A8 重构) — 修正记录写入 Markdown 笔记。

端点:
- POST /api/correction/submit — 提交用户修正 → 追加到 user/corrections.md
"""
from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core.auth import AuthUser, get_current_user
from dependencies import get_memory_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/correction", tags=["correction"])


class CorrectionSubmitRequest(BaseModel):
    """用户修正提交请求。"""
    field_id: str
    agent_value: str
    user_value: str
    context: str = ""  # 可选上下文说明


@router.post("/submit")
async def submit_correction(
    req: CorrectionSubmitRequest,
    user: AuthUser = Depends(get_current_user),
):
    """
    提交用户修正。

    修正记录追加到用户层 corrections.md 笔记文件。
    """
    store = get_memory_store()

    date_str = time.strftime("%Y-%m-%d")
    entry = (
        f"## 修正: {req.field_id} ({date_str})\n"
        f"- Agent 值: {req.agent_value}\n"
        f"- 用户修正为: {req.user_value}\n"
    )
    if req.context:
        entry += f"- 上下文: {req.context}\n"

    store.write_file(
        scope="user",
        filename="corrections.md",
        content=entry,
        mode="append",
        tenant_id=user.tenant_id,
        user_id=user.user_id,
    )

    logger.info(
        f"Correction recorded to markdown: user={user.user_id}, "
        f"field={req.field_id}, {req.agent_value} → {req.user_value}"
    )

    return {
        "status": "recorded",
        "field_id": req.field_id,
        "message": f"修正已记录: {req.field_id} 「{req.agent_value}」→「{req.user_value}」",
    }
