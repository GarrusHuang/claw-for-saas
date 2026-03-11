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
