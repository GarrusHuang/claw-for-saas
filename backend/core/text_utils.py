"""
文本处理工具函数。

smart_truncate: 智能 head+tail 截断，保留重要尾部信息。
paginate_text: 通用文本分页 (动态页大小 + 换行边界对齐)。
"""

from __future__ import annotations

from dataclasses import dataclass

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


# ─── 通用文本分页 ───


@dataclass
class PaginationResult:
    """分页结果。"""
    text: str           # 当前页文本
    offset: int         # 当前起始偏移
    length: int         # 当前页长度
    total_chars: int    # 原始总字符数
    has_more: bool      # 是否有下一页
    next_offset: int | None  # 下一页偏移


def paginate_text(
    text: str,
    offset: int = 0,
    limit: int = 0,
    context_window: int = 32000,
) -> PaginationResult:
    """
    通用文本分页。

    - limit=0: 使用动态页大小 (context_window * 0.2 * 4, 范围 50K-512K)
    - limit>0: 使用用户指定的页大小
    - limit=-1: 不分页，返回从 offset 开始的全部文本
    - 自动对齐换行边界
    """
    total_chars = len(text)

    # limit=-1: 不分页
    if limit == -1:
        page = text[offset:] if offset > 0 else text
        return PaginationResult(
            text=page,
            offset=offset,
            length=len(page),
            total_chars=total_chars,
            has_more=False,
            next_offset=None,
        )

    # 计算页大小
    dynamic_page = int(context_window * 0.2 * 4)
    page_size = max(50000, min(512000, dynamic_page))
    if limit > 0:
        page_size = limit

    # 不需要分页
    if total_chars <= page_size and offset == 0:
        return PaginationResult(
            text=text,
            offset=0,
            length=total_chars,
            total_chars=total_chars,
            has_more=False,
            next_offset=None,
        )

    # 分页: 对齐到换行边界
    end = min(offset + page_size, total_chars)
    if end < total_chars:
        newline_pos = text.rfind("\n", offset, end)
        if newline_pos > offset:
            end = newline_pos + 1

    page = text[offset:end]
    has_more = end < total_chars

    return PaginationResult(
        text=page,
        offset=offset,
        length=len(page),
        total_chars=total_chars,
        has_more=has_more,
        next_offset=end if has_more else None,
    )
