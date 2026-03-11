"""Tests for agent/safe_eval.py — sandboxed expression evaluator."""
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.safe_eval import safe_eval, ALLOWED_BUILTINS, FORBIDDEN_IDENTIFIERS


class TestSafeEvalBasic:
    def test_empty_expression(self):
        assert safe_eval("") is True

    def test_whitespace_expression(self):
        assert safe_eval("   ") is True

    def test_simple_true(self):
        assert safe_eval("True") is True

    def test_simple_false(self):
        assert safe_eval("False") is False

    def test_arithmetic(self):
        assert safe_eval("1 + 1 == 2") is True

    def test_string_comparison(self):
        assert safe_eval("'hello' == 'hello'") is True

    def test_len_allowed(self):
        assert safe_eval("len([1,2,3]) == 3") is True

    def test_context_variable(self):
        assert safe_eval("x > 5", {"x": 10}) is True

    def test_context_variable_false(self):
        assert safe_eval("x > 5", {"x": 3}) is False

    def test_dict_get(self):
        assert safe_eval("tool_input.get('key', '') == 'value'", {"tool_input": {"key": "value"}}) is True

    def test_isinstance_allowed(self):
        assert safe_eval("isinstance(x, int)", {"x": 42}) is True


class TestSafeEvalForbidden:
    def test_dunder_forbidden(self):
        with pytest.raises(ValueError, match="Forbidden"):
            safe_eval("__import__('os')")

    def test_import_forbidden(self):
        with pytest.raises(ValueError, match="Forbidden"):
            safe_eval("import os")

    def test_exec_forbidden(self):
        with pytest.raises(ValueError, match="Forbidden"):
            safe_eval("exec('print(1)')")

    def test_eval_forbidden(self):
        with pytest.raises(ValueError, match="Forbidden"):
            safe_eval("eval('1+1')")

    def test_open_forbidden(self):
        with pytest.raises(ValueError, match="Forbidden"):
            safe_eval("open('/etc/passwd')")

    def test_getattr_forbidden(self):
        with pytest.raises(ValueError, match="Forbidden"):
            safe_eval("getattr(x, 'y')", {"x": {}})

    def test_globals_forbidden(self):
        with pytest.raises(ValueError, match="Forbidden"):
            safe_eval("globals()")

    def test_breakpoint_forbidden(self):
        with pytest.raises(ValueError, match="Forbidden"):
            safe_eval("breakpoint()")


class TestSafeEvalNoFalsePositive:
    def test_tool_input_not_blocked(self):
        """'tool_input' contains 'input' but should NOT be blocked."""
        result = safe_eval("tool_input.get('field', '') != ''", {"tool_input": {"field": "data"}})
        assert result is True

    def test_variable_with_eval_substring(self):
        """'evaluation' contains 'eval' but should NOT be blocked as identifier."""
        result = safe_eval("evaluation == 'pass'", {"evaluation": "pass"})
        assert result is True


class TestSafeEvalErrors:
    def test_runtime_error(self):
        with pytest.raises(ValueError, match="evaluation failed"):
            safe_eval("x / 0", {"x": 1})

    def test_undefined_variable(self):
        with pytest.raises(ValueError, match="evaluation failed"):
            safe_eval("undefined_var > 0")
