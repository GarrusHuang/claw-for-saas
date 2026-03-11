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
    from core.sandbox import SandboxManager
    from core.data_lock import DataLockRegistry
    from services.file_service import FileService
    from services.browser_service import BrowserService
    from skills.loader import SkillLoader
    from memory.markdown_store import MarkdownMemoryStore

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

# Plan step tracker
if TYPE_CHECKING:
    from agent.plan_tracker import PlanTracker

current_plan_tracker: contextvars.ContextVar[PlanTracker | None] = contextvars.ContextVar(
    "current_plan_tracker", default=None
)

# Known field IDs — 供 known_values_guard hook 使用
current_known_field_ids: contextvars.ContextVar[set] = contextvars.ContextVar(
    "current_known_field_ids"
)

# Business context — 供子智能体继承
current_business_context: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "current_business_context", default=None
)

# Memory system ContextVar (A8: Markdown 分层笔记)
current_memory_store: contextvars.ContextVar[MarkdownMemoryStore | None] = contextvars.ContextVar(
    "current_memory_store", default=None
)

# A6: Security Sandbox
current_sandbox: contextvars.ContextVar[SandboxManager | None] = contextvars.ContextVar(
    "current_sandbox", default=None
)

# A6: Data Lock Registry
current_data_lock: contextvars.ContextVar[DataLockRegistry | None] = contextvars.ContextVar(
    "current_data_lock", default=None
)
