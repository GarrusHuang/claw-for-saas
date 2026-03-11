"""Tests for core/errors.py — ErrorCategory, AgentError, classify_error."""
import asyncio
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.errors import ErrorCategory, AgentError, classify_error


class TestErrorCategory:
    def test_values(self):
        assert ErrorCategory.RATE_LIMIT.value == "rate_limit"
        assert ErrorCategory.AUTH.value == "auth"
        assert ErrorCategory.INTERNAL.value == "internal"

    def test_is_string_enum(self):
        assert isinstance(ErrorCategory.RATE_LIMIT, str)


class TestAgentError:
    def test_default_recoverable(self):
        # RATE_LIMIT is in _RECOVERABLE_CATEGORIES
        e = AgentError("limited", category=ErrorCategory.RATE_LIMIT)
        assert e.recoverable is True

        # AUTH is NOT recoverable by default
        e2 = AgentError("bad key", category=ErrorCategory.AUTH)
        assert e2.recoverable is False

    def test_explicit_recoverable_override(self):
        e = AgentError("custom", category=ErrorCategory.AUTH, recoverable=True)
        assert e.recoverable is True

    def test_suggested_action(self):
        e = AgentError("limit", category=ErrorCategory.RATE_LIMIT)
        assert "等待" in e.suggested_action or "重试" in e.suggested_action

    def test_to_error_event(self):
        e = AgentError(
            "test error",
            category=ErrorCategory.TOOL_ERROR,
            affected_step="step1",
        )
        event = e.to_error_event(trace_id="abc")
        assert event["code"] == "TOOL_ERROR"
        assert event["message"] == "test error"
        assert event["recoverable"] is False  # TOOL_ERROR not in recoverable set
        assert event["trace_id"] == "abc"
        assert event["affected_step"] == "step1"

    def test_exception_inheritance(self):
        e = AgentError("test")
        assert isinstance(e, Exception)
        assert str(e) == "test"


class TestClassifyError:
    def test_status_429(self):
        assert classify_error(status_code=429) == ErrorCategory.RATE_LIMIT

    def test_status_401(self):
        assert classify_error(status_code=401) == ErrorCategory.AUTH

    def test_status_403(self):
        assert classify_error(status_code=403) == ErrorCategory.AUTH

    def test_status_503(self):
        assert classify_error(status_code=503) == ErrorCategory.OVERLOADED

    def test_status_500(self):
        assert classify_error(status_code=500) == ErrorCategory.LLM_ERROR

    def test_status_400(self):
        assert classify_error(status_code=400) == ErrorCategory.VALIDATION

    def test_context_overflow_keywords(self):
        assert classify_error(error_msg="context_length exceeded") == ErrorCategory.CONTEXT_OVERFLOW
        assert classify_error(error_msg="too many tokens") == ErrorCategory.CONTEXT_OVERFLOW

    def test_rate_limit_keywords(self):
        assert classify_error(error_msg="rate limit reached") == ErrorCategory.RATE_LIMIT

    def test_network_keywords(self):
        assert classify_error(error_msg="connection refused") == ErrorCategory.NETWORK

    def test_default_internal(self):
        assert classify_error() == ErrorCategory.INTERNAL

    def test_exception_timeout(self):
        assert classify_error(exception=asyncio.TimeoutError()) == ErrorCategory.TOOL_TIMEOUT

    def test_exception_httpx_connect(self):
        import httpx
        exc = httpx.ConnectError("failed")
        assert classify_error(exception=exc) == ErrorCategory.NETWORK
