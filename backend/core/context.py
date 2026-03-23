"""
请求上下文: RequestContext 统一上下文 (无旧 ContextVar)。

用法:
    from core.context import get_request_context
    ctx = get_request_context()
    ctx.event_bus.emit(...)

Gateway 在 _setup_context_vars() 中创建 RequestContext 并注入 current_request。
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
    from agent.plan_tracker import PlanTracker


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
    diff_tracker: Any = None  # TurnDiffTracker | None
    deferred_tools: list = field(default_factory=list)  # list[RegisteredTool]
    subagent_depth: int = 0  # 3.3: 子 Agent 嵌套深度


current_request: contextvars.ContextVar[RequestContext | None] = contextvars.ContextVar(
    "current_request", default=None
)


def get_request_context() -> RequestContext:
    """获取当前请求上下文，未设置时抛出 RuntimeError。"""
    ctx = current_request.get()
    if ctx is None:
        raise RuntimeError("RequestContext not set — 只能在 Gateway 请求链路内调用")
    return ctx
