"""
A9: 定时调度工具 — Agent 可创建/查看/删除定时任务。

通过 current_scheduler ContextVar 访问 Scheduler 实例。
"""

from __future__ import annotations

import logging
import uuid

from croniter import croniter

from core.context import current_scheduler, current_tenant_id, current_user_id
from core.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)

schedule_capability_registry = ToolRegistry()


@schedule_capability_registry.tool(
    description=(
        "创建定时调度任务。"
        "使用标准 cron 表达式定义执行周期, 每次触发时自动以指定消息调用 Agent。"
        "示例 cron: '0 9 * * 1-5' = 工作日每天 9 点, '0 */2 * * *' = 每 2 小时。"
    ),
    read_only=False,
)
def create_schedule(
    name: str,              # 任务名称
    cron: str,              # 5-field cron 表达式
    message: str,           # 每次触发时发送给 Agent 的消息
    business_type: str = "scheduled_task",  # 业务类型
) -> dict:
    """创建定时调度任务。"""
    scheduler = current_scheduler.get(None)
    if not scheduler:
        return {"error": "调度器未初始化"}

    # 验证 cron 表达式
    if not croniter.is_valid(cron):
        return {"error": f"无效的 cron 表达式: {cron}"}

    tenant_id = current_tenant_id.get("default")
    user_id = current_user_id.get("anonymous")

    from core.scheduler import ScheduledTask
    task = ScheduledTask(
        id=str(uuid.uuid4())[:8],
        name=name,
        cron=cron,
        message=message,
        user_id=user_id,
        tenant_id=tenant_id,
        business_type=business_type,
    )

    try:
        task = scheduler.add_task(task)
        return {
            "status": "created",
            "task_id": task.id,
            "name": task.name,
            "cron": task.cron,
            "next_run_at": task.next_run_at,
        }
    except Exception as e:
        logger.error(f"create_schedule error: {e}")
        return {"error": str(e)}


@schedule_capability_registry.tool(
    description=(
        "查看当前用户的定时调度任务列表。"
        "返回所有任务的名称、cron 表达式、状态、上次执行时间等信息。"
    ),
    read_only=True,
)
def list_schedules() -> dict:
    """列出当前用户的定时任务。"""
    scheduler = current_scheduler.get(None)
    if not scheduler:
        return {"error": "调度器未初始化"}

    tenant_id = current_tenant_id.get("default")
    user_id = current_user_id.get("anonymous")

    try:
        tasks = scheduler.list_tasks(tenant_id, user_id)
        return {
            "tasks": [
                {
                    "task_id": t.id,
                    "name": t.name,
                    "cron": t.cron,
                    "message": t.message,
                    "enabled": t.enabled,
                    "last_run_at": t.last_run_at,
                    "last_run_status": t.last_run_status,
                    "next_run_at": t.next_run_at,
                }
                for t in tasks
            ],
            "total": len(tasks),
        }
    except Exception as e:
        logger.error(f"list_schedules error: {e}")
        return {"error": str(e)}


@schedule_capability_registry.tool(
    description=(
        "删除指定的定时调度任务。"
        "需要提供 task_id, 可通过 list_schedules 查询。"
    ),
    read_only=False,
)
def delete_schedule(
    task_id: str,  # 要删除的任务 ID
) -> dict:
    """删除定时任务。"""
    scheduler = current_scheduler.get(None)
    if not scheduler:
        return {"error": "调度器未初始化"}

    tenant_id = current_tenant_id.get("default")
    user_id = current_user_id.get("anonymous")

    try:
        ok = scheduler.remove_task(tenant_id, user_id, task_id)
        if ok:
            return {"status": "deleted", "task_id": task_id}
        return {"error": f"任务不存在: {task_id}"}
    except Exception as e:
        logger.error(f"delete_schedule error: {e}")
        return {"error": str(e)}
