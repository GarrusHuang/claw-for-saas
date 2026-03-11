"""Tests for core/token_estimator.py."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.token_estimator import estimate_tokens, estimate_messages_tokens, _is_cjk


class TestIsCjk:
    def test_chinese_chars(self):
        assert _is_cjk("中") is True
        assert _is_cjk("国") is True

    def test_ascii_chars(self):
        assert _is_cjk("a") is False
        assert _is_cjk("1") is False
        assert _is_cjk(" ") is False

    def test_cjk_punctuation(self):
        assert _is_cjk("。") is True  # CJK Symbols (U+3002)
        assert _is_cjk("、") is True  # U+3001

    def test_fullwidth_forms(self):
        assert _is_cjk("Ａ") is True  # Fullwidth A (U+FF21)


class TestEstimateTokens:
    def test_empty_string(self):
        assert estimate_tokens("") == 0

    def test_pure_english(self):
        # "hello world" = 11 chars -> ~2.75 tokens -> 3
        result = estimate_tokens("hello world")
        assert result > 0
        assert result < 11  # Should be less than char count

    def test_pure_chinese(self):
        # "你好世界" = 4 chars -> ~3.08 tokens -> 3
        result = estimate_tokens("你好世界")
        assert result > 0
        assert result <= 4

    def test_mixed_content(self):
        text = "Hello 你好 World 世界"
        result = estimate_tokens(text)
        assert result > 0

    def test_minimum_one_token(self):
        assert estimate_tokens("a") >= 1


class TestEstimateMessagesTokens:
    def test_single_message(self):
        msgs = [{"role": "user", "content": "hello"}]
        result = estimate_messages_tokens(msgs)
        # 4 (overhead) + tokens("hello")
        assert result > 4

    def test_multiple_messages(self):
        msgs = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hi"},
        ]
        result = estimate_messages_tokens(msgs)
        assert result > 8  # At least 2 * 4 overhead

    def test_with_tools(self):
        msgs = [{"role": "user", "content": "hi"}]
        tools = [{"type": "function", "function": {"name": "calc", "parameters": {}}}]
        without_tools = estimate_messages_tokens(msgs)
        with_tools = estimate_messages_tokens(msgs, tools=tools)
        assert with_tools > without_tools

    def test_empty_messages(self):
        assert estimate_messages_tokens([]) == 0

    def test_message_with_tool_calls(self):
        msgs = [{
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": "calc", "arguments": "{}"}}],
        }]
        result = estimate_messages_tokens(msgs)
        assert result > 4  # overhead + tool_calls serialization
