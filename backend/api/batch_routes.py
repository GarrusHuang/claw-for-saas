"""
#22 Batch Jobs API — 批量任务端点。
"""

from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends
from pydantic import BaseModel

router = APIRouter(prefix="/api/batch", tags=["batch"])


class BatchRequest(BaseModel):
    items: list[str]
    business_type: str = "batch"


class BatchStatusResponse(BaseModel):
    job_id: str
    status: str
    total: int
    completed: int
    failed: int


@router.post("")
async def submit_batch(req: BatchRequest):
    """提交批量任务。"""
    from dependencies import build_gateway
    from services.batch_service import BatchService
    from core.auth import get_current_user_from_request

    # 简化：从默认配置获取 tenant/user
    from config import settings
    tenant_id = settings.auth_default_tenant_id
    user_id = settings.auth_default_user_id

    gateway = build_gateway()
    svc = BatchService()
    job_id = f"batch_{uuid.uuid4().hex[:8]}"
    job = await svc.submit(
        job_id=job_id, inputs=req.items, gateway=gateway,
        tenant_id=tenant_id, user_id=user_id,
        business_type=req.business_type,
    )
    return {
        "job_id": job.job_id,
        "status": job.status,
        "total": len(job.items),
        "results": [
            {"index": item.index, "status": item.status, "result": item.result}
            for item in job.items
        ],
    }
