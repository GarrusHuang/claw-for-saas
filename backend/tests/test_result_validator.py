"""Tests for agent/result_validator.py — ToolResultValidator."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.result_validator import ToolResultValidator, ValidationRule


def test_unknown_tool_valid():
    v = ToolResultValidator()
    valid, warning = v.validate("nonexistent_tool", "anything")
    assert valid is True
    assert warning == ""


def test_classify_type_with_type_valid():
    v = ToolResultValidator()
    valid, warning = v.validate("classify_type", '{"type": "差旅报销"}')
    assert valid is True
    assert warning == ""


def test_classify_type_missing_type_invalid():
    v = ToolResultValidator()
    valid, warning = v.validate("classify_type", '{"name": "foo"}')
    assert valid is False
    assert "缺少关键内容" in warning or "missing" in warning.lower()


def test_sum_values_numeric_valid():
    v = ToolResultValidator()
    valid, warning = v.validate("sum_values", "123.45")
    assert valid is True


def test_sum_values_no_digits_invalid():
    v = ToolResultValidator()
    valid, warning = v.validate("sum_values", "no numbers here")
    assert valid is False


def test_result_exceeding_max_len_invalid():
    v = ToolResultValidator()
    long_result = "type " * 200  # > 500 chars for classify_type max_len
    valid, warning = v.validate("classify_type", long_result)
    assert valid is False
    assert "过长" in warning


def test_custom_extra_rules():
    extra = {"my_tool": ValidationRule(must_contain=["status"], max_len=100)}
    v = ToolResultValidator(extra_rules=extra)
    valid, warning = v.validate("my_tool", '{"status": "ok"}')
    assert valid is True

    valid2, warning2 = v.validate("my_tool", '{"result": "ok"}')
    assert valid2 is False


def test_get_rule_unknown():
    v = ToolResultValidator()
    assert v.get_rule("unknown_tool") is None


def test_get_rule_known():
    v = ToolResultValidator()
    rule = v.get_rule("classify_type")
    assert rule is not None
    assert "type" in rule.must_contain
