"""
A9: 定时调度引擎。

基于 cron 表达式周期性触发 Agent 执行。
- asyncio 后台循环 (60s tick)
- croniter 计算下次执行时间
- 直接调用 gateway.chat() (无 HTTP 开销)
- JSON 持久化 data/schedules/{tenant_id}/{user_id}/tasks.json
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any, Callable, Awaitable

from croniter import croniter

logger = logging.getLogger(__name__)


@dataclass
class RunRecord:
    """单次执行记录。"""
    started_at: float
    status: str               # "success" | "failed"
    duration_s: float
    session_id: str = ""
    trigger: str = "scheduled"  # "scheduled" | "manual"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> RunRecord:
        return cls(
            started_at=data.get("started_at", 0),
            status=data.get("status", ""),
            duration_s=data.get("duration_s", 0),
            session_id=data.get("session_id", ""),
            trigger=data.get("trigger", "scheduled"),
        )


@dataclass
class ScheduledTask:
    """定时任务定义。"""
    id: str
    name: str
    cron: str                       # 5-field cron expression (空 = 一次性任务)
    message: str                    # 发送给 Agent 的消息
    user_id: str
    tenant_id: str
    business_type: str = "scheduled_task"
    timezone: str = ""              # IANA tz name (e.g. "Asia/Shanghai"), 空则用系统配置
    enabled: bool = True
    created_at: float = field(default_factory=time.time)
    last_run_at: float | None = None
    last_run_status: str = ""       # "success" | "failed" | ""
    next_run_at: float | None = None
    scheduled_at: float | None = None   # 一次性任务: 执行时间戳 (cron 为空时使用)
    expires_at: float | None = None     # 到期时间，到期后自动 disable
    run_history: list[dict] = field(default_factory=list)  # RunRecord 列表 (最多 50 条)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> ScheduledTask:
        return cls(
            id=data["id"],
            name=data["name"],
            cron=data.get("cron", ""),
            message=data["message"],
            user_id=data["user_id"],
            tenant_id=data["tenant_id"],
            business_type=data.get("business_type", "scheduled_task"),
            timezone=data.get("timezone", ""),
            enabled=data.get("enabled", True),
            created_at=data.get("created_at", time.time()),
            last_run_at=data.get("last_run_at"),
            last_run_status=data.get("last_run_status", ""),
            next_run_at=data.get("next_run_at"),
            scheduled_at=data.get("scheduled_at"),
            expires_at=data.get("expires_at"),
            run_history=data.get("run_history", []),
        )


def compute_next_run(cron_expr: str, base_time: float | None = None, tz_name: str | None = None) -> float:
    """计算 cron 表达式的下次执行时间，使用指定时区解释 cron。

    Args:
        cron_expr: 5-field cron expression
        base_time: 基准时间 (Unix epoch seconds), 默认 now
        tz_name: IANA 时区名 (如 "Asia/Shanghai"), 默认从配置读取
    """
    if tz_name is None:
        from config import Settings
        tz_name = Settings().scheduler_timezone
    tz = ZoneInfo(tz_name)
    base = datetime.fromtimestamp(base_time or time.time(), tz=tz)
    cron = croniter(cron_expr, base)
    return cron.get_next(float)


class ScheduleStore:
    """JSON 持久化 — data/schedules/{tenant_id}/{user_id}/tasks.json。"""

    def __init__(self, base_dir: str) -> None:
        self.base_dir = Path(base_dir)

    def _tasks_path(self, tenant_id: str, user_id: str) -> Path:
        return self.base_dir / tenant_id / user_id / "tasks.json"

    def _load_tasks(self, tenant_id: str, user_id: str) -> list[ScheduledTask]:
        path = self._tasks_path(tenant_id, user_id)
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return [ScheduledTask.from_dict(t) for t in data]
        except Exception as e:
            logger.error(f"Failed to load tasks for {tenant_id}/{user_id}: {e}")
            return []

    def _save_tasks(self, tenant_id: str, user_id: str, tasks: list[ScheduledTask]) -> None:
        path = self._tasks_path(tenant_id, user_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps([t.to_dict() for t in tasks], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add(self, task: ScheduledTask) -> None:
        tasks = self._load_tasks(task.tenant_id, task.user_id)
        tasks.append(task)
        self._save_tasks(task.tenant_id, task.user_id, tasks)

    def remove(self, tenant_id: str, user_id: str, task_id: str) -> bool:
        tasks = self._load_tasks(tenant_id, user_id)
        before = len(tasks)
        tasks = [t for t in tasks if t.id != task_id]
        if len(tasks) == before:
            return False
        self._save_tasks(tenant_id, user_id, tasks)
        return True

    def get(self, tenant_id: str, user_id: str, task_id: str) -> ScheduledTask | None:
        for t in self._load_tasks(tenant_id, user_id):
            if t.id == task_id:
                return t
        return None

    def update(self, task: ScheduledTask) -> None:
        tasks = self._load_tasks(task.tenant_id, task.user_id)
        for i, t in enumerate(tasks):
            if t.id == task.id:
                tasks[i] = task
                break
        self._save_tasks(task.tenant_id, task.user_id, tasks)

    def list_tasks(self, tenant_id: str, user_id: str) -> list[ScheduledTask]:
        return self._load_tasks(tenant_id, user_id)

    def list_all_tasks(self) -> list[ScheduledTask]:
        """遍历所有租户/用户目录，加载全部任务。"""
        all_tasks: list[ScheduledTask] = []
        if not self.base_dir.exists():
            return all_tasks
        for tenant_dir in self.base_dir.iterdir():
            if not tenant_dir.is_dir():
                continue
            for user_dir in tenant_dir.iterdir():
                if not user_dir.is_dir():
                    continue
                all_tasks.extend(self._load_tasks(tenant_dir.name, user_dir.name))
        return all_tasks


# Type alias for gateway factory
GatewayFactory = Callable[[], Any]


class Scheduler:
    """
    asyncio 后台调度器。

    - start() 加载磁盘任务 + 启动后台 tick
    - stop() 取消后台任务
    - _tick() 每 N 秒检查到期任务
    """

    def __init__(
        self,
        store: ScheduleStore,
        gateway_factory: GatewayFactory,
        webhook_dispatcher: Any | None = None,
        notification_manager: Any | None = None,
        check_interval_s: int = 60,
    ) -> None:
        self.store = store
        self.gateway_factory = gateway_factory
        self.webhook_dispatcher = webhook_dispatcher
        self.notification_manager = notification_manager
        self.check_interval_s = check_interval_s
        self._tasks: dict[str, ScheduledTask] = {}  # task_id → task
        self._bg_task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        """启动调度器: 加载全部任务 + 创建后台 tick。"""
        all_tasks = self.store.list_all_tasks()
        for task in all_tasks:
            if task.enabled:
                # 计算 next_run_at
                if task.next_run_at is None:
                    if task.cron:
                        task.next_run_at = compute_next_run(task.cron, tz_name=task.timezone or None)
                    elif task.scheduled_at:
                        task.next_run_at = task.scheduled_at
                    self.store.update(task)
                self._tasks[task.id] = task
        logger.info(f"Scheduler started with {len(self._tasks)} active tasks")
        self._running = True
        self._bg_task = asyncio.create_task(self._tick_loop())

    async def stop(self) -> None:
        """停止调度器。"""
        self._running = False
        if self._bg_task:
            self._bg_task.cancel()
            try:
                await self._bg_task
            except asyncio.CancelledError:
                pass
        logger.info("Scheduler stopped")

    async def _tick_loop(self) -> None:
        """后台循环: 每 check_interval_s 检查到期任务。"""
        while self._running:
            try:
                await self._tick()
            except Exception as e:
                logger.error(f"Scheduler tick error: {e}")
            await asyncio.sleep(self.check_interval_s)

    async def _tick(self) -> None:
        """检查到期任务，创建执行协程。"""
        now = time.time()
        for task_id, task in list(self._tasks.items()):
            if not task.enabled:
                continue
            # 检查到期时间
            if task.expires_at and task.expires_at <= now:
                logger.info(f"Task expired, disabling: {task.name} ({task.id})")
                task.enabled = False
                self.store.update(task)
                self._tasks.pop(task_id, None)
                continue
            if task.next_run_at and task.next_run_at <= now:
                logger.info(f"Triggering scheduled task: {task.name} ({task.id})")
                # 立即更新 next_run_at 防止下次 tick 重复触发
                if task.cron:
                    task.next_run_at = compute_next_run(task.cron, tz_name=task.timezone or None)
                else:
                    # 一次性任务: 清除 next_run_at，执行后 disable
                    task.next_run_at = None
                self.store.update(task)
                t = asyncio.create_task(self._execute_task(task))
                t.add_done_callback(self._task_done_callback)

    def _task_done_callback(self, task: asyncio.Task) -> None:
        """Log exceptions from fire-and-forget tasks."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.error(f"Scheduled task execution failed: {exc}", exc_info=exc)

    def _append_run_record(self, task: ScheduledTask, record: RunRecord) -> None:
        """追加运行记录，FIFO 保留最多 50 条。"""
        task.run_history.append(record.to_dict())
        if len(task.run_history) > 50:
            task.run_history = task.run_history[-50:]

    async def _execute_task(self, task: ScheduledTask, trigger: str = "scheduled") -> None:
        """执行定时任务: 调用 gateway.chat() → 更新状态 → 触发 webhook。"""
        started_at = time.time()
        try:
            gateway = self.gateway_factory()
            result = await gateway.chat(
                tenant_id=task.tenant_id,
                user_id=task.user_id,
                message=task.message,
                business_type=task.business_type,
            )

            task.last_run_at = time.time()
            task.last_run_status = "success" if not result.get("error") else "failed"

            # 追加运行记录
            self._append_run_record(task, RunRecord(
                started_at=started_at,
                status=task.last_run_status,
                duration_s=round(task.last_run_at - started_at, 1),
                session_id=result.get("session_id", ""),
                trigger=trigger,
            ))

            # 一次性任务执行后 disable
            if not task.cron:
                task.enabled = False
                self._tasks.pop(task.id, None)
            else:
                task.next_run_at = compute_next_run(task.cron, tz_name=task.timezone or None)
            self.store.update(task)

            # Webhook 通知
            if self.webhook_dispatcher:
                event = "task_completed" if task.last_run_status == "success" else "task_failed"
                await self.webhook_dispatcher.dispatch(
                    tenant_id=task.tenant_id,
                    event=event,
                    data={
                        "task_id": task.id,
                        "task_name": task.name,
                        "status": task.last_run_status,
                        "answer": result.get("answer", ""),
                    },
                )

            logger.info(f"Scheduled task completed: {task.name} → {task.last_run_status}")

            # WebSocket 通知用户
            if self.notification_manager:
                await self.notification_manager.notify_user(task.user_id, "session_created", {
                    "session_id": result.get("session_id", ""),
                    "task_name": task.name,
                    "status": task.last_run_status,
                    "source": "scheduled_task",
                })

        except Exception as e:
            logger.error(f"Scheduled task failed: {task.name} — {e}")
            task.last_run_at = time.time()
            task.last_run_status = "failed"

            # 追加失败运行记录
            self._append_run_record(task, RunRecord(
                started_at=started_at,
                status="failed",
                duration_s=round(task.last_run_at - started_at, 1),
                session_id="",
                trigger=trigger,
            ))

            if not task.cron:
                task.enabled = False
                self._tasks.pop(task.id, None)
            else:
                task.next_run_at = compute_next_run(task.cron, tz_name=task.timezone or None)
            self.store.update(task)

            if self.webhook_dispatcher:
                await self.webhook_dispatcher.dispatch(
                    tenant_id=task.tenant_id,
                    event="task_failed",
                    data={
                        "task_id": task.id,
                        "task_name": task.name,
                        "status": "failed",
                        "error": str(e),
                    },
                )

    async def run_task_now(self, tenant_id: str, user_id: str, task_id: str) -> bool:
        """立即触发执行任务 (trigger=manual)，不影响定时计划。"""
        task = self.store.get(tenant_id, user_id, task_id)
        if not task:
            return False
        t = asyncio.create_task(self._execute_task(task, trigger="manual"))
        t.add_done_callback(self._task_done_callback)
        return True

    def add_task(self, task: ScheduledTask) -> ScheduledTask:
        """添加定时任务。"""
        if task.cron:
            task.next_run_at = compute_next_run(task.cron, tz_name=task.timezone or None)
        elif task.scheduled_at:
            task.next_run_at = task.scheduled_at
        self.store.add(task)
        if task.enabled:
            self._tasks[task.id] = task
        return task

    def remove_task(self, tenant_id: str, user_id: str, task_id: str) -> bool:
        """删除定时任务。"""
        ok = self.store.remove(tenant_id, user_id, task_id)
        self._tasks.pop(task_id, None)
        return ok

    def list_tasks(self, tenant_id: str, user_id: str) -> list[ScheduledTask]:
        """列出用户的定时任务。"""
        return self.store.list_tasks(tenant_id, user_id)

    def get_task(self, tenant_id: str, user_id: str, task_id: str) -> ScheduledTask | None:
        """获取单个定时任务。"""
        return self.store.get(tenant_id, user_id, task_id)

    def pause_task(self, tenant_id: str, user_id: str, task_id: str) -> bool:
        """暂停定时任务。"""
        task = self.store.get(tenant_id, user_id, task_id)
        if not task:
            return False
        task.enabled = False
        self.store.update(task)
        self._tasks.pop(task_id, None)
        return True

    def resume_task(self, tenant_id: str, user_id: str, task_id: str) -> bool:
        """恢复定时任务。"""
        task = self.store.get(tenant_id, user_id, task_id)
        if not task:
            return False
        task.enabled = True
        if task.cron:
            task.next_run_at = compute_next_run(task.cron, tz_name=task.timezone or None)
        elif task.scheduled_at:
            task.next_run_at = task.scheduled_at
        self.store.update(task)
        self._tasks[task.id] = task
        return True

    def update_task(
        self, tenant_id: str, user_id: str, task_id: str, **kwargs
    ) -> ScheduledTask | None:
        """更新定时任务字段。"""
        task = self.store.get(tenant_id, user_id, task_id)
        if not task:
            return None
        for key, val in kwargs.items():
            if hasattr(task, key) and key not in ("id", "user_id", "tenant_id", "created_at"):
                setattr(task, key, val)
        if "cron" in kwargs or "scheduled_at" in kwargs:
            if task.cron:
                task.next_run_at = compute_next_run(task.cron, tz_name=task.timezone or None)
            elif task.scheduled_at:
                task.next_run_at = task.scheduled_at
            else:
                task.next_run_at = None
        self.store.update(task)
        # 更新内存
        if task.enabled:
            self._tasks[task.id] = task
        else:
            self._tasks.pop(task.id, None)
        return task
