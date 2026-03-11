"""Tests for agent/pre_compact.py — pre_compact_hook."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.hooks import HookEvent, HookResult
from agent.pre_compact import pre_compact_hook


def _make_event(messages):
    return HookEvent(
        event_type="pre_compact",
        session_id="s1",
        user_id="u1",
        context={"messages_to_compact": messages},
    )


def test_empty_messages_allow():
    event = _make_event([])
    result = pre_compact_hook(event)
    assert result.action == "allow"


def test_known_value_preserved():
    event = _make_event([{"role": "assistant", "content": "field set via known_value"}])
    result = pre_compact_hook(event)
    assert result.action == "modify"
    assert "[PRESERVED known_value]" in result.message


def test_user_correction_preserved():
    event = _make_event([{"role": "user", "content": "用户修正: 金额应该是500"}])
    result = pre_compact_hook(event)
    assert result.action == "modify"
    assert "[PRESERVED correction]" in result.message


def test_audit_conclusion_preserved():
    event = _make_event([{"role": "tool", "content": "审计结论: 不通过"}])
    result = pre_compact_hook(event)
    assert result.action == "modify"
    assert "[PRESERVED audit]" in result.message


def test_correction_keyword_preserved():
    event = _make_event([{"role": "user", "content": "correction needed for amount"}])
    result = pre_compact_hook(event)
    assert result.action == "modify"
    assert "[PRESERVED correction]" in result.message


def test_multiple_preserved_items():
    event = _make_event([
        {"role": "assistant", "content": "field from known_value source"},
        {"role": "user", "content": "用户修正: change amount"},
        {"role": "tool", "content": "审计结论: pass"},
    ])
    result = pre_compact_hook(event)
    assert result.action == "modify"
    assert "[PRESERVED known_value]" in result.message
    assert "[PRESERVED correction]" in result.message
    assert "[PRESERVED audit]" in result.message


def test_regular_message_allow():
    event = _make_event([{"role": "user", "content": "hello world, nothing special"}])
    result = pre_compact_hook(event)
    assert result.action == "allow"


# ─── custom 模式测试 ───


def _make_custom_event(messages, custom_patterns):
    return HookEvent(
        event_type="pre_compact",
        session_id="s1",
        user_id="u1",
        context={
            "messages_to_compact": messages,
            "protection_mode": "custom",
            "custom_patterns": custom_patterns,
        },
    )


def test_custom_mode_matches_user_patterns():
    """custom 模式用用户提供的正则提取标识符。"""
    event = _make_custom_event(
        [{"role": "assistant", "content": "订单号 ORD-20250101-001 已创建"}],
        [r"ORD-\d{8}-\d{3}"],
    )
    result = pre_compact_hook(event)
    assert result.action == "modify"
    assert "[PRESERVED identifiers]" in result.message
    assert "ORD-20250101-001" in result.message


def test_custom_mode_no_builtin_patterns():
    """custom 模式不使用内置 ID/金额/日期正则。"""
    # 内容含有金额和日期，但 custom 模式只用用户正则
    event = _make_custom_event(
        [{"role": "assistant", "content": "金额 ¥1234.56，日期 2025-03-11"}],
        [r"TICKET-\d+"],  # 不匹配任何内容
    )
    result = pre_compact_hook(event)
    # 没有 known_value/correction/audit 关键词，用户正则也不匹配 → allow
    assert result.action == "allow"


def test_custom_mode_multiple_patterns():
    """custom 模式支持多个正则。"""
    event = _make_custom_event(
        [{"role": "assistant", "content": "员工 EMP-007 报销单 REP-2025-042"}],
        [r"EMP-\d+", r"REP-\d{4}-\d{3}"],
    )
    result = pre_compact_hook(event)
    assert result.action == "modify"
    assert "EMP-007" in result.message
    assert "REP-2025-042" in result.message


def test_custom_mode_preserves_known_value():
    """custom 模式下 known_value 关键词保护仍然生效。"""
    event = _make_custom_event(
        [{"role": "assistant", "content": "field set via known_value"}],
        [],  # 无自定义正则
    )
    result = pre_compact_hook(event)
    assert result.action == "modify"
    assert "[PRESERVED known_value]" in result.message


def test_custom_mode_preserves_correction():
    """custom 模式下用户修正保护仍然生效。"""
    event = _make_custom_event(
        [{"role": "user", "content": "用户修正: 数量改为10"}],
        [],
    )
    result = pre_compact_hook(event)
    assert result.action == "modify"
    assert "[PRESERVED correction]" in result.message


def test_custom_mode_preserves_audit():
    """custom 模式下审计结论保护仍然生效。"""
    event = _make_custom_event(
        [{"role": "tool", "content": "审计结论: 不通过"}],
        [],
    )
    result = pre_compact_hook(event)
    assert result.action == "modify"
    assert "[PRESERVED audit]" in result.message


def test_custom_mode_empty_patterns_allow():
    """custom 模式无正则且无关键词 → allow。"""
    event = _make_custom_event(
        [{"role": "user", "content": "hello world, nothing special"}],
        [],
    )
    result = pre_compact_hook(event)
    assert result.action == "allow"


def test_custom_mode_invalid_regex_skipped():
    """custom 模式下无效正则被跳过，不影响其他正则。"""
    event = _make_custom_event(
        [{"role": "assistant", "content": "单号 ABC-123 处理完成"}],
        [r"[invalid(", r"ABC-\d+"],  # 第一个无效，第二个有效
    )
    result = pre_compact_hook(event)
    assert result.action == "modify"
    assert "ABC-123" in result.message


def test_custom_mode_dedup_identifiers():
    """custom 模式下重复标识符会去重。"""
    event = _make_custom_event(
        [
            {"role": "assistant", "content": "处理 TK-001"},
            {"role": "assistant", "content": "再次处理 TK-001"},
        ],
        [r"TK-\d+"],
    )
    result = pre_compact_hook(event)
    assert result.action == "modify"
    # TK-001 只出现一次
    assert result.message.count("TK-001") == 1
