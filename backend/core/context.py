"""
请求上下文: contextvars 注入。

工具通过 contextvars 获取 EventBus/user_id/session_id，
无需在函数签名中显式传参。

Usage:
    from core.context import current_event_bus, current_user_id, current_session_id

    # 在 Gateway 入口设置
    current_event_bus.set(event_bus)
    current_user_id.set("U001")
    current_session_id.set("sess-xxx")

    # 在工具中获取
    bus = current_event_bus.get()
    bus.emit("field_update", {...})
"""

from __future__ import annotations

import contextvars
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.event_bus import EventBus
    from services.file_service import FileService
    from services.browser_service import BrowserService
    from skills.loader import SkillLoader
    from memory.learning import LearningMemory
    from memory.correction import CorrectionMemory

current_tenant_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_tenant_id", default="default"
)

current_event_bus: contextvars.ContextVar[EventBus | None] = contextvars.ContextVar(
    "current_event_bus", default=None
)

current_user_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_user_id", default="anonymous"
)

current_session_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_session_id", default=""
)

current_skill_loader: contextvars.ContextVar[SkillLoader | None] = contextvars.ContextVar(
    "current_skill_loader", default=None
)

current_file_service: contextvars.ContextVar[FileService | None] = contextvars.ContextVar(
    "current_file_service", default=None
)

current_browser_service: contextvars.ContextVar[BrowserService | None] = contextvars.ContextVar(
    "current_browser_service", default=None
)

# Protected field IDs — agent cannot override these values
current_protected_field_ids: contextvars.ContextVar[set] = contextvars.ContextVar(
    "current_protected_field_ids"
)

# Request trace ID
current_trace_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_trace_id", default=""
)

# Business context (for subagent inheritance)
current_business_context: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "current_business_context", default=None
)

# Plan step tracker
if TYPE_CHECKING:
    from agent.plan_tracker import PlanTracker

current_plan_tracker: contextvars.ContextVar[PlanTracker | None] = contextvars.ContextVar(
    "current_plan_tracker", default=None
)

# Memory system ContextVars
current_learning_memory: contextvars.ContextVar[LearningMemory | None] = contextvars.ContextVar(
    "current_learning_memory", default=None
)

current_correction_memory: contextvars.ContextVar[CorrectionMemory | None] = contextvars.ContextVar(
    "current_correction_memory", default=None
)
