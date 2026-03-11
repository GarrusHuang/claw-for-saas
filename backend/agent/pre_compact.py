"""
上下文压缩安全 — A4 增强。

PreCompact Hook: 在上下文压缩前检查，保护关键信息不被丢弃。

保护策略 (4e: 标识符保护):
1. strict 模式: 保留所有标识符 (ID、金额、日期) + known_values + 修正 + 审计
2. custom 模式: 通过配置指定保护的字段
3. off 模式: 不保护

默认 strict 模式。
"""

from __future__ import annotations

import logging
import re

from agent.hooks import HookEvent, HookResult

logger = logging.getLogger(__name__)

# ─── 标识符正则模式 ───

# 各类业务 ID (UUID, 数字ID, 编号等)
_ID_PATTERN = re.compile(
    r'\b(?:id|ID|Id|编号|单号|工号|账号)["\s:=]*["\']?([A-Za-z0-9_-]{4,36})["\']?'
)

# 金额 (¥123.45, $1,234.56, 123.45元)
_AMOUNT_PATTERN = re.compile(
    r'[¥$￥]\s*[\d,]+\.?\d*|[\d,]+\.?\d*\s*[元块]'
)

# 日期 (2025-01-15, 2025/01/15, 2025年1月15日)
_DATE_PATTERN = re.compile(
    r'\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?'
)


def _extract_identifiers(text: str) -> list[str]:
    """从文本中提取标识符 (ID、金额、日期)。"""
    found = []
    for match in _ID_PATTERN.finditer(text):
        found.append(match.group(0)[:100])
    for match in _AMOUNT_PATTERN.finditer(text):
        found.append(match.group(0))
    for match in _DATE_PATTERN.finditer(text):
        found.append(match.group(0))
    return found


def _extract_custom_identifiers(text: str, patterns: list[str]) -> list[str]:
    """用用户提供的正则列表从文本中提取匹配项。"""
    found = []
    for pat_str in patterns:
        try:
            pat = re.compile(pat_str)
        except re.error:
            logger.warning(f"PreCompact custom: 无效正则跳过: {pat_str!r}")
            continue
        for match in pat.finditer(text):
            found.append(match.group(0)[:100])
    return found


def pre_compact_hook(event: HookEvent) -> HookResult:
    """
    上下文压缩前检查 (A4: 4e — strict / custom / off 模式)。

    扫描待压缩的消息，提取需要保护的关键信息:
    1. known_value 来源的字段更新 (所有模式)
    2. 用户修正记录 (所有模式)
    3. 审计关键决策 (所有模式)
    4. 业务标识符:
       - strict: 内置 ID/金额/日期正则
       - custom: 用户通过 context["custom_patterns"] 提供正则列表
       - off: 不保护

    Returns:
        - action="modify" + message=保护内容前缀 (如果有需要保护的内容)
        - action="allow" (没有需要保护的内容)
    """
    messages = event.context.get("messages_to_compact", [])
    if not messages:
        return HookResult(action="allow")

    # 检查保护模式 (默认 strict)
    protection_mode = event.context.get("protection_mode", "strict")
    if protection_mode == "off":
        return HookResult(action="allow")

    # custom 模式需要 custom_patterns
    custom_patterns: list[str] = []
    if protection_mode == "custom":
        custom_patterns = event.context.get("custom_patterns", [])

    preserved_parts = []
    identifiers_found = []

    for msg in messages:
        content = str(msg.get("content", ""))
        role = msg.get("role", "")

        # 保护 known_value 来源的字段更新 (不受模式影响)
        if "known_value" in content or re.search(r"source.*known", content, re.IGNORECASE):
            preserved_parts.append(f"[PRESERVED known_value] {content[:200]}")

        # 保护用户修正 (不受模式影响)
        if any(kw in content for kw in ("用户修正", "correction", "用户纠正", "更正为")):
            preserved_parts.append(f"[PRESERVED correction] {content[:200]}")

        # 保护审计关键结论 (不受模式影响)
        if role == "tool" and any(kw in content for kw in ("审计结论", "audit_result", "不通过", "不合规")):
            preserved_parts.append(f"[PRESERVED audit] {content[:200]}")

        # 标识符提取: strict 用内置正则, custom 用用户正则
        if protection_mode == "strict":
            ids = _extract_identifiers(content)
            identifiers_found.extend(ids)
        elif protection_mode == "custom" and custom_patterns:
            ids = _extract_custom_identifiers(content, custom_patterns)
            identifiers_found.extend(ids)

    # 去重标识符
    if identifiers_found:
        unique_ids = list(dict.fromkeys(identifiers_found))[:20]  # 最多 20 个
        preserved_parts.append(
            "[PRESERVED identifiers] " + " | ".join(unique_ids)
        )

    if preserved_parts:
        prefix = "\n".join(preserved_parts)
        logger.info(
            f"PreCompact: 保护了 {len(preserved_parts)} 条关键信息 "
            f"(mode={protection_mode})"
        )
        return HookResult(
            action="modify",
            message=prefix,
        )

    return HookResult(action="allow")
