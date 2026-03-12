"""
Token 估算器 — 中英混合字符启发式估算 + 消息级缓存。

用于 ReAct 循环中的上下文预算检查，避免 LLM 上下文窗口溢出。
无外部依赖（不需要 tiktoken），纯字符统计。

估算规则:
- 英文/ASCII: ~4 字符 = 1 token
- 中文/CJK: ~1.3 字符 = 1 token
- JSON/工具结果: ~2 字符 = 1 token (更保守)
- JSON 结构开销: 每条消息 ~4 tokens (role/content 标记)
- 工具 schema: 直接序列化后用文本估算

A4 增强:
- 消息级缓存 (content hash → token count)
- 差量估算 (新增消息只估算增量)
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from functools import lru_cache


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


def estimate_tokens_conservative(text: str) -> int:
    """
    更保守的 token 估算 — 用于 JSON/工具结果。

    JSON 内容空白和结构符号多，用 ~2 字符/token 估算。
    """
    if not text:
        return 0
    return max(1, len(text) // 2)


# ─── 消息级缓存 (A4: 4g) ───

_msg_token_cache: dict[str, int] = {}
_CACHE_MAX_SIZE = 2000
_cache_created_at: float = 0.0
_CACHE_TTL_S = 3600  # 1 hour


def _msg_cache_key(msg: dict) -> str:
    """生成消息的缓存 key (基于内容 hash)。"""
    content = msg.get("content", "")
    role = msg.get("role", "")
    tool_calls = msg.get("tool_calls")
    # 用 role + content 前 64 字符 + content 长度 + hash 做 key
    # 避免对超长内容做完整 hash
    content_str = str(content)
    prefix = content_str[:64]
    if tool_calls:
        tc_str = json.dumps(tool_calls, ensure_ascii=False, default=str)
        sig = hashlib.md5(f"{role}:{content_str}:{tc_str}".encode(), usedforsecurity=False).hexdigest()[:12]
    else:
        sig = hashlib.md5(f"{role}:{content_str}".encode(), usedforsecurity=False).hexdigest()[:12]
    return f"{role}:{len(content_str)}:{sig}"


def _estimate_single_message_tokens(msg: dict) -> int:
    """估算单条消息的 token 数 (带缓存)。"""
    global _msg_token_cache, _cache_created_at

    now = time.time()
    if _cache_created_at == 0.0:
        _cache_created_at = now
    elif now - _cache_created_at > _CACHE_TTL_S:
        _msg_token_cache.clear()
        _cache_created_at = now

    key = _msg_cache_key(msg)
    if key in _msg_token_cache:
        return _msg_token_cache[key]

    # 消息结构开销
    total = 4

    # content (A4-4i: 支持 list 多模态 content blocks)
    content = msg.get("content", "")
    if content:
        role = msg.get("role", "")
        if isinstance(content, list):
            # 多模态 content blocks
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        total += estimate_tokens(block.get("text", ""))
                    elif block.get("type") == "image_url":
                        total += 256  # 保守估算: 图片 ~256 tokens
        elif role == "tool":
            total += estimate_tokens_conservative(str(content))
        else:
            total += estimate_tokens(str(content))

    # tool_calls (assistant 消息中)
    tool_calls = msg.get("tool_calls", [])
    if tool_calls:
        tc_text = json.dumps(tool_calls, ensure_ascii=False, default=str)
        total += estimate_tokens_conservative(tc_text)

    # 缓存 (FIFO 批量清理: 超限时删除前半部分)
    if len(_msg_token_cache) >= _CACHE_MAX_SIZE:
        # 清掉前半部分
        keys = list(_msg_token_cache.keys())
        for k in keys[:_CACHE_MAX_SIZE // 2]:
            del _msg_token_cache[k]

    _msg_token_cache[key] = total
    return total


def estimate_messages_tokens(
    messages: list[dict],
    tools: list[dict] | None = None,
) -> int:
    """
    估算完整 messages 数组 + 工具 schema 的 token 数量。

    A4 增强: 消息级缓存 + 工具结果保守估算。

    Args:
        messages: OpenAI 格式的消息列表
        tools: 可选的工具 schema 列表

    Returns:
        估算的总 token 数量
    """
    total = 0

    for msg in messages:
        total += _estimate_single_message_tokens(msg)

    # 工具 schema 开销
    if tools:
        tools_text = json.dumps(tools, ensure_ascii=False, default=str)
        total += estimate_tokens(tools_text)

    return total


def invalidate_cache() -> None:
    """清空 token 估算缓存。"""
    global _msg_token_cache, _cache_created_at
    _msg_token_cache.clear()
    _cache_created_at = 0.0
