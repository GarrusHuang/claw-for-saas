"""
请求上下文: contextvars 注入。

**推荐方式** (P.2):
    from core.context import get_request_context
    ctx = get_request_context()
    ctx.event_bus.emit(...)

**兼容方式** (旧工具仍使用):
    from core.context import current_event_bus, current_user_id, current_session_id
    bus = current_event_bus.get()

Gateway 在 _setup_context_vars() 中同时设置 RequestContext 和旧 ContextVar，
工具层逐步迁移到 RequestContext。
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from core.event_bus import EventBus
    from core.sandbox import SandboxManager
    from core.data_lock import DataLockRegistry
    from core.scheduler import Scheduler
    from services.file_service import FileService
    from services.browser_service import BrowserService
    from skills.loader import SkillLoader
    from memory.markdown_store import MarkdownMemoryStore


# ── RequestContext: 聚合所有请求级依赖 ──


@dataclass
class RequestContext:
    """一次请求的完整上下文，替代 16 个独立 ContextVar 的逐个注入。"""

    tenant_id: str = "default"
    user_id: str = "anonymous"
    session_id: str = ""
    event_bus: Any = None  # EventBus | None
    skill_loader: Any = None  # SkillLoader | None
    file_service: Any = None  # FileService | None
    browser_service: Any = None  # BrowserService | None
    memory_store: Any = None  # MarkdownMemoryStore | None
    sandbox: Any = None  # SandboxManager | None
    data_lock: Any = None  # DataLockRegistry | None
    mcp_provider: Any = None
    scheduler: Any = None  # Scheduler | None
    subagent_runner: Any = None
    known_field_ids: set = field(default_factory=set)
    plan_tracker: Any = None  # PlanTracker | None


current_request: contextvars.ContextVar[RequestContext | None] = contextvars.ContextVar(
    "current_request", default=None
)


def get_request_context() -> RequestContext:
    """获取当前请求上下文，未设置时抛出 RuntimeError。"""
    ctx = current_request.get()
    if ctx is None:
        raise RuntimeError("RequestContext not set — 只能在 Gateway 请求链路内调用")
    return ctx

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
    "current_protected_field_ids", default=set()
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

# A2: MCP Provider (SaaS 宿主注入业务数据拉取接口)
current_mcp_provider: contextvars.ContextVar[Any] = contextvars.ContextVar(
    "current_mcp_provider", default=None
)

# A9: Scheduler
current_scheduler: contextvars.ContextVar[Scheduler | None] = contextvars.ContextVar(
    "current_scheduler", default=None
)
