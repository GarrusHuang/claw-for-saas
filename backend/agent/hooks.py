"""
Hooks 系统 — 对标 Claude Code 的 PreToolUse / PostToolUse / Stop。

在 Agent 生命周期关键节点执行自定义逻辑:
- pre_tool_use: 工具调用前 (可阻止/修改参数)
- post_tool_use: 工具调用后 (审计日志/结果转换)
- agent_stop: Agent 结束时 (清理/保存状态)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

KNOWN_EVENT_TYPES = {"pre_tool_use", "post_tool_use", "agent_stop", "agent_completed", "pre_compact"}


@dataclass
class HookEvent:
    """Hook 事件数据。"""
    event_type: str  # "pre_tool_use" | "post_tool_use" | "agent_stop" | "pre_compact"
    tool_name: str = ""
    tool_input: dict = field(default_factory=dict)
    tool_output: str = ""
    session_id: str = ""
    user_id: str = ""
    runtime_steps: list = field(default_factory=list)  # Stop hook: 检查工具调用历史
    context: dict = field(default_factory=dict)  # 通用上下文 (PreCompact 等)


@dataclass
class HookResult:
    """Hook 执行结果。"""
    action: str = "allow"  # "allow" | "block" | "modify"
    message: str = ""
    modified_input: dict | None = None


@dataclass
class _HookHandler:
    """已注册的 hook handler。"""
    handler: Callable[[HookEvent], HookResult | Awaitable[HookResult]]
    matcher: str | None = None  # 可按工具名过滤


class HookRegistry:
    """
    Hook 注册与分发。

    Usage:
        hooks = HookRegistry()
        hooks.register("pre_tool_use", my_guard, matcher="update_form_field")
        result = await hooks.fire(HookEvent("pre_tool_use", tool_name="update_form_field"))
        if result.action == "block":
            return f"blocked: {result.message}"
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[_HookHandler]] = {
            "pre_tool_use": [],
            "post_tool_use": [],
            "agent_stop": [],
            "pre_compact": [],
        }

    def register(
        self,
        event_type: str,
        handler: Callable[[HookEvent], HookResult | Awaitable[HookResult]],
        matcher: str | None = None,
    ) -> None:
        """注册 hook handler。matcher 可按工具名过滤。"""
        if event_type not in KNOWN_EVENT_TYPES:
            logger.warning(f"Registering hook for unknown event_type: {event_type!r}")
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(_HookHandler(handler=handler, matcher=matcher))

    async def fire(self, event: HookEvent) -> HookResult:
        """触发 hook，返回最终决策 (block 优先 > modify > allow)。"""
        import asyncio

        handlers = self._handlers.get(event.event_type, [])
        modify_result: HookResult | None = None

        for h in handlers:
            # matcher 过滤
            if h.matcher and event.tool_name and h.matcher != event.tool_name:
                continue

            try:
                result = h.handler(event)
                if asyncio.iscoroutine(result):
                    result = await result
                if result and result.action == "block":
                    logger.info(f"Hook blocked {event.event_type}:{event.tool_name}: {result.message}")
                    return result
                if result and result.action == "modify" and modify_result is None:
                    modify_result = result
            except Exception as e:
                logger.error(f"Hook error in {event.event_type}: {e}")

        # 返回 modify 结果 (如有)，否则 allow
        return modify_result or HookResult(action="allow")


# ── 内置 Hooks ──


def known_values_guard(event: HookEvent) -> HookResult:
    """
    阻止覆盖 known_values 中的字段。

    通过 contextvars 中的 current_known_field_ids 检查
    (由 Gateway 在请求入口设置)。
    """
    from core.context import current_known_field_ids

    field_id = event.tool_input.get("field_id", "")
    try:
        known_ids = current_known_field_ids.get()
    except LookupError:
        known_ids = set()

    if field_id in known_ids and event.tool_input.get("source") != "known_value":
        return HookResult(
            action="block",
            message=f"字段 {field_id} 是 known_value，不可被 Agent 覆盖。",
        )
    return HookResult(action="allow")


def audit_logger(event: HookEvent) -> HookResult:
    """记录所有工具调用到日志。"""
    logger.info(
        f"[AUDIT] {event.event_type} tool={event.tool_name} "
        f"user={event.user_id} session={event.session_id}"
    )
    return HookResult(action="allow")


# ── Phase 27: 编码工具安全 Hook ──

# 命令黑名单模式
_COMMAND_BLACKLIST = [
    r"rm\s+-rf\s+/",
    r"rm\s+-rf\s+~",
    r"\bsudo\b",
    r"\bcurl\b.*\|\s*sh",
    r"\bwget\b.*\|\s*sh",
    r"\bmkfs\b",
    r":\(\)\s*\{",        # fork bomb
    r"\bdd\s+if=",
    r"\bchmod\s+777\s+/",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\binit\s+0\b",
]

# 敏感文件名模式 (禁止写入)
_SENSITIVE_FILES = [
    ".env", ".env.local", ".env.production",
    "credentials", "credentials.json",
    "id_rsa", "id_ed25519", "id_ecdsa",
    ".pem", ".key", ".p12", ".pfx",
    "shadow", "passwd",
]


def code_safety_hook(event: HookEvent) -> HookResult:
    """
    编码工具安全检查 (pre_tool_use)。

    - read_source_file / write_source_file: 敏感文件保护
    - write_source_file: 禁止写入敏感文件 (.env, credentials, private keys)
    - run_command: 命令黑名单检查
    """
    import re

    tool = event.tool_name
    if tool not in ("read_source_file", "write_source_file", "run_command"):
        return HookResult(action="allow")

    # ── 写入敏感文件检查 ──
    if tool == "write_source_file":
        path = event.tool_input.get("path", "")
        basename = path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower()
        for sensitive in _SENSITIVE_FILES:
            if basename == sensitive or basename.endswith(sensitive):
                return HookResult(
                    action="block",
                    message=f"安全检查: 禁止写入敏感文件 {path}",
                )

    # ── 命令黑名单检查 ──
    if tool == "run_command":
        command = event.tool_input.get("command", "")
        for pattern in _COMMAND_BLACKLIST:
            if re.search(pattern, command, re.IGNORECASE):
                return HookResult(
                    action="block",
                    message=f"安全检查: 命令包含危险操作 — {command[:100]}",
                )

    return HookResult(action="allow")


def build_default_hooks() -> HookRegistry:
    """构建默认 hook 注册表。"""
    registry = HookRegistry()
    registry.register("post_tool_use", audit_logger)
    registry.register("pre_tool_use", known_values_guard, matcher="update_form_field")
    # Phase 15: 上下文压缩安全
    from agent.pre_compact import pre_compact_hook
    registry.register("pre_compact", pre_compact_hook)
    # Phase 11: 自验证质量门
    from agent.quality_gate import quality_gate_hook
    registry.register("agent_stop", quality_gate_hook)
    # Phase 17: 安全防护 Hook
    from agent.security_hooks import parameter_validation_hook, sensitive_data_hook, data_lock_hook
    registry.register("pre_tool_use", parameter_validation_hook)
    registry.register("post_tool_use", sensitive_data_hook)
    # A6: DataLock 字段锁定校验
    registry.register("pre_tool_use", data_lock_hook)
    # Phase 27: 编码工具安全 Hook (no matcher — checks tool_name internally)
    registry.register("pre_tool_use", code_safety_hook)
    return registry
