"""
上下文压缩安全 — Phase 15。

PreCompact Hook: 在上下文压缩前检查，保护关键信息不被丢弃。

保护策略:
1. 提取 messages 中的 known_value 来源的字段更新
2. 提取用户修正记录 (correction events)
3. 将保护内容注入到压缩摘要前缀

用法:
    在 _compact_messages 调用前触发 pre_compact 事件，
    将 HookResult.message 作为摘要前缀注入。
"""

from __future__ import annotations

import logging

import re

from agent.hooks import HookEvent, HookResult

logger = logging.getLogger(__name__)


def pre_compact_hook(event: HookEvent) -> HookResult:
    """
    上下文压缩前检查。

    扫描待压缩的消息，提取需要保护的关键信息:
    1. known_value 来源的字段更新 (不可被 Agent 覆盖的值)
    2. 用户修正记录 (用户偏好和纠正)
    3. 审计关键决策 (通过/不通过 + 原因)

    Returns:
        - action="modify" + message=保护内容前缀 (如果有需要保护的内容)
        - action="allow" (没有需要保护的内容)
    """
    messages = event.context.get("messages_to_compact", [])
    if not messages:
        return HookResult(action="allow")

    preserved_parts = []

    for msg in messages:
        content = str(msg.get("content", ""))
        role = msg.get("role", "")

        # 保护 known_value 来源的字段更新
        if "known_value" in content or re.search(r"source.*known", content, re.IGNORECASE):
            preserved_parts.append(f"[PRESERVED known_value] {content[:200]}")

        # 保护用户修正
        if any(kw in content for kw in ("用户修正", "correction", "用户纠正", "更正为")):
            preserved_parts.append(f"[PRESERVED correction] {content[:200]}")

        # 保护审计关键结论
        if role == "tool" and any(kw in content for kw in ("审计结论", "audit_result", "不通过", "不合规")):
            preserved_parts.append(f"[PRESERVED audit] {content[:200]}")

    if preserved_parts:
        prefix = "\n".join(preserved_parts)
        logger.info(f"PreCompact: 保护了 {len(preserved_parts)} 条关键信息")
        return HookResult(
            action="modify",
            message=prefix,
        )

    return HookResult(action="allow")
