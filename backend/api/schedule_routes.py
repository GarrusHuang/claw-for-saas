"""
A9: 调度 API — 定时任务 CRUD + 暂停/恢复。
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.auth import AuthUser, get_current_user
from dependencies import get_scheduler

router = APIRouter(prefix="/api/schedules", tags=["schedules"])


class ScheduleCreateRequest(BaseModel):
    name: str
    cron: str
    message: str
    business_type: str = "scheduled_task"


class ScheduleUpdateRequest(BaseModel):
    name: str | None = None
    cron: str | None = None
    message: str | None = None
    business_type: str | None = None
    enabled: bool | None = None


@router.get("")
async def list_schedules(user: AuthUser = Depends(get_current_user)):
    """列出用户的定时任务。"""
    scheduler = get_scheduler()
    tasks = scheduler.list_tasks(user.tenant_id, user.user_id)
    return {
        "tasks": [t.to_dict() for t in tasks],
        "total": len(tasks),
    }


@router.post("")
async def create_schedule(req: ScheduleCreateRequest, user: AuthUser = Depends(get_current_user)):
    """创建定时任务。"""
    from croniter import croniter
    if not croniter.is_valid(req.cron):
        raise HTTPException(status_code=400, detail=f"Invalid cron expression: {req.cron}")

    from core.scheduler import ScheduledTask
    task = ScheduledTask(
        id=str(uuid.uuid4())[:8],
        name=req.name,
        cron=req.cron,
        message=req.message,
        user_id=user.user_id,
        tenant_id=user.tenant_id,
        business_type=req.business_type,
    )

    scheduler = get_scheduler()
    task = scheduler.add_task(task)
    return task.to_dict()


@router.get("/{task_id}")
async def get_schedule(task_id: str, user: AuthUser = Depends(get_current_user)):
    """获取定时任务详情。"""
    scheduler = get_scheduler()
    task = scheduler.get_task(user.tenant_id, user.user_id, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task.to_dict()


@router.put("/{task_id}")
async def update_schedule(
    task_id: str,
    req: ScheduleUpdateRequest,
    user: AuthUser = Depends(get_current_user),
):
    """更新定时任务。"""
    if req.cron is not None:
        from croniter import croniter
        if not croniter.is_valid(req.cron):
            raise HTTPException(status_code=400, detail=f"Invalid cron expression: {req.cron}")

    scheduler = get_scheduler()
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    task = scheduler.update_task(user.tenant_id, user.user_id, task_id, **updates)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task.to_dict()


@router.delete("/{task_id}")
async def delete_schedule(task_id: str, user: AuthUser = Depends(get_current_user)):
    """删除定时任务。"""
    scheduler = get_scheduler()
    ok = scheduler.remove_task(user.tenant_id, user.user_id, task_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "deleted", "task_id": task_id}


@router.post("/{task_id}/pause")
async def pause_schedule(task_id: str, user: AuthUser = Depends(get_current_user)):
    """暂停定时任务。"""
    scheduler = get_scheduler()
    ok = scheduler.pause_task(user.tenant_id, user.user_id, task_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "paused", "task_id": task_id}


@router.post("/{task_id}/resume")
async def resume_schedule(task_id: str, user: AuthUser = Depends(get_current_user)):
    """恢复定时任务。"""
    scheduler = get_scheduler()
    ok = scheduler.resume_task(user.tenant_id, user.user_id, task_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "resumed", "task_id": task_id}
