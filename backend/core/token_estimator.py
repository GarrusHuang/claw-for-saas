"""
Token 估算器 — 中英混合字符启发式估算。

用于 ReAct 循环中的上下文预算检查，避免 LLM 上下文窗口溢出。
无外部依赖（不需要 tiktoken），纯字符统计。

估算规则:
- 英文/ASCII: ~4 字符 = 1 token
- 中文/CJK: ~1.3 字符 = 1 token
- JSON 结构开销: 每条消息 ~4 tokens (role/content 标记)
- 工具 schema: 直接序列化后用文本估算
"""

from __future__ import annotations

import json
import re


def _is_cjk(char: str) -> bool:
    """判断字符是否为 CJK (中日韩) 字符。"""
    cp = ord(char)
    return (
        (0x4E00 <= cp <= 0x9FFF)       # CJK Unified Ideographs
        or (0x3400 <= cp <= 0x4DBF)    # CJK Unified Ideographs Extension A
        or (0x20000 <= cp <= 0x2A6DF)  # CJK Unified Ideographs Extension B
        or (0x2A700 <= cp <= 0x2B73F)  # CJK Unified Ideographs Extension C
        or (0x2B740 <= cp <= 0x2B81F)  # CJK Unified Ideographs Extension D
        or (0x3000 <= cp <= 0x303F)    # CJK Symbols and Punctuation
        or (0xFF00 <= cp <= 0xFFEF)    # Halfwidth and Fullwidth Forms
        or (0xF900 <= cp <= 0xFAFF)    # CJK Compatibility Ideographs
    )


def estimate_tokens(text: str) -> int:
    """
    估算文本的 token 数量。

    中英混合文本启发式:
    - 英文/ASCII 字符: ~4 字符/token
    - 中文/CJK 字符: ~1.3 字符/token (即每个汉字约 0.77 token)
    - 标点和空白: 按英文处理

    Args:
        text: 要估算的文本

    Returns:
        估算的 token 数量
    """
    if not text:
        return 0

    cjk_count = 0
    ascii_count = 0

    for char in text:
        if _is_cjk(char):
            cjk_count += 1
        else:
            ascii_count += 1

    # 英文 ~4 char/token, 中文 ~1.3 char/token
    cjk_tokens = cjk_count / 1.3
    ascii_tokens = ascii_count / 4.0

    return max(1, int(cjk_tokens + ascii_tokens + 0.5))


def estimate_messages_tokens(
    messages: list[dict],
    tools: list[dict] | None = None,
) -> int:
    """
    估算完整 messages 数组 + 工具 schema 的 token 数量。

    每条消息有 ~4 tokens 的结构开销 (role, content 标记等)。
    工具 schema 序列化后按文本估算。

    Args:
        messages: OpenAI 格式的消息列表
        tools: 可选的工具 schema 列表

    Returns:
        估算的总 token 数量
    """
    total = 0

    for msg in messages:
        # 消息结构开销: role + content 标记
        total += 4

        # content
        content = msg.get("content", "")
        if content:
            total += estimate_tokens(str(content))

        # tool_calls (assistant 消息中)
        tool_calls = msg.get("tool_calls", [])
        if tool_calls:
            tc_text = json.dumps(tool_calls, ensure_ascii=False, default=str)
            total += estimate_tokens(tc_text)

    # 工具 schema 开销
    if tools:
        tools_text = json.dumps(tools, ensure_ascii=False, default=str)
        total += estimate_tokens(tools_text)

    return total
