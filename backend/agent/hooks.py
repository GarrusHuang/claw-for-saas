"""
Hooks 系统 — 对标 Claude Code 的 PreToolUse / PostToolUse / Stop。

在 Agent 生命周期关键节点执行自定义逻辑:
- pre_tool_use: 工具调用前 (可阻止/修改参数)
- post_tool_use: 工具调用后 (审计日志/结果转换)
- agent_stop: Agent 结束时 (清理/保存状态)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

KNOWN_EVENT_TYPES = {
    "pre_tool_use", "post_tool_use", "agent_stop", "agent_completed",
    "pre_compact", "user_prompt_submit", "session_start",
}


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
    action: str = "allow"  # "allow" | "block" | "modify" | "inject"
    message: str = ""  # block/inject 时的消息 (inject: 注入到对话中的 developer instruction)
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
        """触发 hook，返回最终决策 (block 优先 > inject > modify > allow)。"""
        import asyncio

        handlers = self._handlers.get(event.event_type, [])
        modify_result: HookResult | None = None
        inject_result: HookResult | None = None

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
                if result and result.action == "inject" and inject_result is None:
                    inject_result = result
                if result and result.action == "modify" and modify_result is None:
                    modify_result = result
            except Exception as e:
                logger.error(f"Hook error in {event.event_type}: {e}")

        # 优先级: inject > modify > allow
        return inject_result or modify_result or HookResult(action="allow")


# ── 内置 Hooks ──


def known_values_guard(event: HookEvent) -> HookResult:
    """
    阻止覆盖 known_values 中的字段。

    通过 RequestContext.known_field_ids 检查
    (由 Gateway 在请求入口设置)。

    注: 当前 known_field_ids 始终为空集合 — 需要 MCP 集成后
    由 Gateway 从 get_protected_values() 响应填充。
    在此之前本 hook 是 no-op 但保留框架以备 MCP 激活。
    """
    from core.context import current_request

    field_id = event.tool_input.get("field_id", "")
    ctx = current_request.get()
    known_ids = ctx.known_field_ids if ctx else set()

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


# ── Phase 27: 编码工具安全 Hook (委托 ExecPolicy) ──

from core.exec_policy import ExecPolicy

_exec_policy = ExecPolicy()


_PATCH_FILE_RE = re.compile(r"\*\*\*\s+(?:Add|Update|Delete)\s+File:\s+(.+)")


def code_safety_hook(event: HookEvent) -> HookResult:
    """
    编码工具安全检查 (pre_tool_use)。

    - write_source_file: 敏感文件保护
    - apply_patch: 从 patch 内容提取所有文件路径，逐一检查敏感文件
    - run_command: 命令安全策略 (三层防御)
    """
    tool = event.tool_name
    if tool not in ("read_source_file", "write_source_file", "run_command", "apply_patch"):
        return HookResult(action="allow")

    _REQUEST_PERMISSIONS_HINT = "如果确需执行，请先调用 request_permissions 工具获取用户授权。"

    # ── 写入敏感文件检查 ──
    if tool == "write_source_file":
        path = event.tool_input.get("path", "")
        if path and _exec_policy.is_sensitive_file(path):
            return HookResult(
                action="block",
                message=f"安全检查: 禁止写入敏感文件 {path}。{_REQUEST_PERMISSIONS_HINT}",
            )

    # ── apply_patch: 提取 patch 内所有文件路径，逐一检查 ──
    if tool == "apply_patch":
        patch_text = event.tool_input.get("patch", "")
        if patch_text:
            for match in _PATCH_FILE_RE.finditer(patch_text):
                file_path = match.group(1).strip()
                if _exec_policy.is_sensitive_file(file_path):
                    return HookResult(
                        action="block",
                        message=f"安全检查: 禁止通过 apply_patch 修改敏感文件 {file_path}。{_REQUEST_PERMISSIONS_HINT}",
                    )

    # ── 命令安全策略检查 (含 per-user 审批持久化 #16) ──
    if tool == "run_command":
        command = event.tool_input.get("command", "")
        from core.context import current_request as _cr
        _ctx = _cr.get()
        _tid = _ctx.tenant_id if _ctx else ""
        _uid = _ctx.user_id if _ctx else event.user_id
        safe, reason = _exec_policy.check_command_with_approval(command, _tid, _uid)
        if not safe:
            # 检查对话中是否有近期用户授权 → 持久化审批并放行
            recent = event.context.get("recent_messages", "")
            if recent and any(kw in recent for kw in ("approved", "授权执行", "允许执行", "确认执行")):
                pattern = " ".join(command.strip().split()[:2]) if command.strip() else ""
                if pattern:
                    _exec_policy.approve_command(_tid, _uid, pattern)
                    logger.info(f"Command approved and persisted: {pattern}")
                # 放行
            else:
                return HookResult(action="block", message=f"{reason}。{_REQUEST_PERMISSIONS_HINT}")

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

    # 3.4: Guardian AI 风险评估 (排在规则 Hook 之后，只评估规则放行的高风险调用)
    try:
        from config import settings as _guardian_settings
        if _guardian_settings.guardian_enabled:
            from agent.guardian import build_guardian_hook
            guardian_handler = build_guardian_hook(_guardian_settings)
            if guardian_handler:
                registry.register("pre_tool_use", guardian_handler)
            # #43: 语义质量检查 (复用 Guardian 开关 — 同样需要 LLM，同一个成本决策)
            from agent.quality_gate import semantic_quality_hook
            registry.register("agent_stop", semantic_quality_hook)
            logger.info("Semantic quality check enabled (guardian_enabled=True)")
    except Exception as e:
        logger.debug(f"Guardian hook registration skipped: {e}")

    # 声明式规则引擎: 加载 data/hook_rules/*.json 中用户定义的规则
    try:
        from agent.hook_rules import HookRuleEngine
        import os
        rules_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "hook_rules")
        engine = HookRuleEngine(rules_dir)
        rule_count = engine.register_all(registry)
        if rule_count:
            logger.info(f"Loaded {rule_count} declarative hook rules from {rules_dir}")
    except Exception as e:
        logger.debug(f"Hook rule engine loading skipped: {e}")

    return registry
