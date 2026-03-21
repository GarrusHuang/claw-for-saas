"""
安全防护 Hook — Phase 17。

PreToolUse 参数安全校验 + PostToolUse 敏感数据检测。
对标 Claude Code 的安全沙箱策略。

检查项:
- URL 参数防止 SSRF (内网地址/localhost)
- file_id/file_path 防止路径穿越
- 数值参数范围检查
- 工具输出敏感数据检测 (仅日志告警，不阻止)
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from agent.hooks import HookEvent, HookResult

logger = logging.getLogger(__name__)


def parameter_validation_hook(event: HookEvent) -> HookResult:
    """
    PreToolUse 参数安全校验。

    检查项:
    1. URL 参数防止 SSRF (内网地址/localhost)
    2. file_id/file_path 参数防止路径穿越
    3. 数值参数范围检查 (金额不超过 1 亿)
    """
    tool_input = event.tool_input

    # 1. URL 安全检查
    for key in ("url", "target_url", "api_url"):
        url = tool_input.get(key, "")
        if url and _is_unsafe_url(url):
            return HookResult(
                action="block",
                message=f"URL 安全检查失败: {url} — 禁止访问内网/本地地址",
            )

    # 2. 路径穿越检查
    for key in ("file_id", "file_path", "filename"):
        path = tool_input.get(key, "")
        if path and _has_path_traversal(path):
            return HookResult(
                action="block",
                message=f"路径安全检查失败: {path} — 检测到路径穿越",
            )

    # 3. 数值范围检查 (金额不超过 1 亿)
    for key in ("value", "amount", "total"):
        val = tool_input.get(key)
        if val is not None:
            try:
                num = float(val)
                if abs(num) > 100_000_000:
                    return HookResult(
                        action="block",
                        message=f"数值超出安全范围: {key}={val} — 绝对值不得超过 1 亿",
                    )
            except (ValueError, TypeError):
                pass  # 非数值类型，跳过检查

    return HookResult(action="allow")


def _is_unsafe_url(url: str) -> bool:
    """检测内网/本地 URL (SSRF 防护)。"""
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
    except Exception:
        return True  # 解析失败视为不安全

    # 本地地址
    unsafe_hosts = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]"}
    if host in unsafe_hosts:
        return True

    # IPv4 内网段
    if host.startswith("10."):
        return True
    if host.startswith("192.168."):
        return True
    if host.startswith("172."):
        # 172.16.0.0 - 172.31.255.255
        parts = host.split(".")
        if len(parts) >= 2:
            try:
                second = int(parts[1])
                if 16 <= second <= 31:
                    return True
            except ValueError:
                pass

    # 链接本地 (IPv4)
    if host.startswith("169.254."):
        return True

    # IPv6 私有/本地段
    # 去掉 [] 包裹 (URL 中 IPv6 用 [::1] 格式)
    bare = host.strip("[]")
    if bare.startswith("fc") or bare.startswith("fd"):
        # fc00::/7 — Unique Local Address (ULA)
        return True
    if bare.startswith("fe80"):
        # fe80::/10 — Link-Local
        return True

    # 元数据服务 (AWS/GCP/Azure)
    if host in ("metadata.google.internal", "169.254.169.254"):
        return True

    return False


def _has_path_traversal(path: str) -> bool:
    """检测路径穿越攻击。"""
    if ".." in path:
        return True
    if path.startswith("/"):
        return True
    if path.startswith("\\"):
        return True
    # Windows 绝对路径
    if len(path) >= 2 and path[1] == ":":
        return True
    return False


def data_lock_hook(event: HookEvent) -> HookResult:
    """
    A6 PreToolUse: DataLock 校验。

    检查写操作是否涉及被锁定的字段。
    readonly 级别阻止, audit 级别记录但放行。
    """
    from core.context import current_request

    ctx = current_request.get()
    registry = ctx.data_lock if ctx else None
    if registry is None:
        return HookResult(action="allow")

    tool_input = event.tool_input

    # 检查所有可能包含字段标识的参数
    field_keys = ("field_id", "field_name", "key", "name")
    for fk in field_keys:
        field_id = tool_input.get(fk, "")
        if not field_id:
            continue
        value = tool_input.get("value", tool_input.get("content", ""))
        violation = registry.check(field_id, str(value) if value else "")
        if violation:
            return HookResult(
                action="block",
                message=f"数据锁定: 字段 '{field_id}' 被锁定 ({violation.level.value}) — {violation.reason}",
            )

    return HookResult(action="allow")


def sensitive_data_hook(event: HookEvent) -> HookResult:
    """
    PostToolUse 敏感数据检测。

    检查工具输出中是否包含敏感信息格式 (身份证号/银行卡号/手机号)。
    不阻止执行，只记录警告日志。
    """
    output = event.tool_output or ""
    if not output:
        return HookResult(action="allow")

    patterns = {
        "身份证号": r"\b\d{17}[\dXx]\b",
        "银行卡号": r"\b\d{16,19}\b",
        "手机号": r"\b1[3-9]\d{9}\b",
    }

    detected = []
    for name, pattern in patterns.items():
        if re.search(pattern, output):
            detected.append(name)

    if detected:
        logger.warning(
            f"[SECURITY] Sensitive data detected in {event.tool_name} output: "
            f"{', '.join(detected)}"
        )

    return HookResult(action="allow")  # 不阻止，只记录
