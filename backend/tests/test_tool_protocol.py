"""Tests for core/tool_protocol.py — ToolCallParser."""
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.tool_protocol import ToolCallParser, ParsedToolCall, ParsedResponse


class TestToolCallParserNativeMode:
    def setup_method(self):
        self.parser = ToolCallParser()

    def test_native_tool_calls(self):
        response = {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_abc",
                    "function": {
                        "name": "calculator",
                        "arguments": '{"expr": "1+1"}',
                    },
                }
            ],
        }
        result = self.parser.parse(response)
        assert result.is_final_answer is False
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "calculator"
        assert result.tool_calls[0].arguments == {"expr": "1+1"}

    def test_native_multiple_calls(self):
        response = {
            "content": "Let me check...",
            "tool_calls": [
                {"id": "c1", "function": {"name": "tool_a", "arguments": "{}"}},
                {"id": "c2", "function": {"name": "tool_b", "arguments": '{"x": 1}'}},
            ],
        }
        result = self.parser.parse(response)
        assert len(result.tool_calls) == 2
        assert result.tool_calls[0].name == "tool_a"
        assert result.tool_calls[1].name == "tool_b"


class TestToolCallParserHermesMode:
    def setup_method(self):
        self.parser = ToolCallParser()

    def test_hermes_xml_tool_call(self):
        response = {
            "content": 'I will use calculator.\n<tool_call>\n{"name": "calculator", "arguments": {"expr": "2+2"}}\n</tool_call>',
            "tool_calls": None,
        }
        result = self.parser.parse(response)
        assert result.is_final_answer is False
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "calculator"
        assert result.tool_calls[0].arguments == {"expr": "2+2"}
        # Content should have the tool_call XML removed
        assert "<tool_call>" not in result.content

    def test_hermes_multiple_calls(self):
        content = (
            '<tool_call>\n{"name": "a", "arguments": {}}\n</tool_call>\n'
            '<tool_call>\n{"name": "b", "arguments": {"k": "v"}}\n</tool_call>'
        )
        response = {"content": content, "tool_calls": None}
        result = self.parser.parse(response)
        assert len(result.tool_calls) == 2

    def test_hermes_with_parameters_key(self):
        response = {
            "content": '<tool_call>\n{"name": "calc", "parameters": {"x": 1}}\n</tool_call>',
            "tool_calls": None,
        }
        result = self.parser.parse(response)
        assert result.tool_calls[0].arguments == {"x": 1}


class TestToolCallParserFinalAnswer:
    def setup_method(self):
        self.parser = ToolCallParser()

    def test_plain_text_is_final_answer(self):
        response = {"content": "The answer is 42.", "tool_calls": None}
        result = self.parser.parse(response)
        assert result.is_final_answer is True
        assert result.content == "The answer is 42."
        assert result.tool_calls == []

    def test_empty_content_is_final_answer(self):
        response = {"content": "", "tool_calls": None}
        result = self.parser.parse(response)
        assert result.is_final_answer is True
        assert result.content == ""


class TestToolCallParserThinking:
    def setup_method(self):
        self.parser = ToolCallParser()

    def test_thinking_extraction(self):
        response = {
            "content": "<think>Let me think...</think>The answer is 42.",
            "tool_calls": None,
        }
        result = self.parser.parse(response)
        assert result.thinking == "Let me think..."
        assert result.content == "The answer is 42."
        assert "<think>" not in result.content

    def test_thinking_with_tool_call(self):
        response = {
            "content": '<think>Reasoning</think>\n<tool_call>\n{"name": "calc", "arguments": {}}\n</tool_call>',
            "tool_calls": None,
        }
        result = self.parser.parse(response)
        assert result.thinking == "Reasoning"
        assert result.is_final_answer is False


class TestSafeParseArguments:
    def setup_method(self):
        self.parser = ToolCallParser()

    def test_valid_json(self):
        assert self.parser._safe_parse_arguments('{"a": 1}') == {"a": 1}

    def test_missing_opening_brace(self):
        assert self.parser._safe_parse_arguments('"a": 1}') == {"a": 1}

    def test_missing_closing_brace(self):
        assert self.parser._safe_parse_arguments('{"a": 1') == {"a": 1}

    def test_missing_both_braces(self):
        assert self.parser._safe_parse_arguments('"a": 1') == {"a": 1}

    def test_empty_string(self):
        assert self.parser._safe_parse_arguments("") == {}
        assert self.parser._safe_parse_arguments("  ") == {}

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError, match="Cannot parse"):
            self.parser._safe_parse_arguments("not json at all {{{}}")
