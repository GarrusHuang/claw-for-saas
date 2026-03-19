"""
文本处理工具函数。

smart_truncate: 智能 head+tail 截断，保留重要尾部信息。
"""

from __future__ import annotations

# ─── 最低保留字符数 ───
_MIN_TRUNCATE_CHARS = 2000


def smart_truncate(text: str, max_chars: int) -> str:
    """
    智能 head+tail 截断 (A4: 4a)。

    策略:
    1. 检测尾部是否有重要内容 (错误信息、JSON 闭合、总结段落)
    2. 有 → 30% 给尾部, 70% 给头部
    3. 无 → 全部给头部
    4. 中间插入截断标记，包含原始总字符数和总行数
    """
    if len(text) <= max_chars:
        return text

    total_chars = len(text)
    total_lines = text.count("\n") + 1

    # 小预算时直接简单截断 (不强制拉高到 _MIN_TRUNCATE_CHARS)
    if max_chars < _MIN_TRUNCATE_CHARS:
        truncated_count = total_chars - max_chars
        return (
            text[:max_chars]
            + f"...[truncated {truncated_count} of {total_chars} chars, {total_lines} lines total]"
        )

    # 检测尾部是否包含重要内容
    # 注: 不再把 }/] 单独作为信号 — 几乎所有 JSON 响应尾部都有闭合标签，
    # 这会导致 has_important_tail 几乎永远为 True。
    # 改为只检测明确的错误/摘要关键词。
    tail_500 = text[-500:] if len(text) > 500 else text
    has_important_tail = any(sig in tail_500 for sig in (
        '"error"', '"Error"', '"status"', '"total"', '"summary"',
        "Exception", "Traceback", "错误", "失败", "总计",
    ))

    # 先估算 marker 长度，纳入预算计算
    truncated_estimate = total_chars - max_chars
    marker_template = "\n...[truncated {} of {} chars, {} lines total]...\n"
    marker = marker_template.format(truncated_estimate, total_chars, total_lines)
    marker_len = len(marker)

    if has_important_tail:
        # 30% 尾部, 70% 头部 (扣除 marker 预算)
        usable = max_chars - marker_len
        tail_budget = int(usable * 0.3)
        head_budget = usable - tail_budget
    else:
        # 全部给头部 (扣除 marker 预算)
        head_budget = max_chars - marker_len
        tail_budget = 0

    head_budget = max(head_budget, 200)

    # 重算实际截断字符数 (marker 文本可能微调)
    truncated_count = total_chars - head_budget - tail_budget
    marker = marker_template.format(truncated_count, total_chars, total_lines)

    if tail_budget > 0:
        return text[:head_budget] + marker + text[-tail_budget:]
    else:
        return text[:head_budget] + marker
