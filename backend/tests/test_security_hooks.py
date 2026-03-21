"""Tests for agent/security_hooks.py — SSRF, path traversal, PII detection."""
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.hooks import HookEvent, HookResult
from agent.security_hooks import (
    parameter_validation_hook,
    sensitive_data_hook,
    data_lock_hook,
    _is_unsafe_url,
    _has_path_traversal,
)


# ── _is_unsafe_url ──


class TestIsUnsafeUrl:
    def test_localhost(self):
        assert _is_unsafe_url("http://localhost/api") is True

    def test_127_0_0_1(self):
        assert _is_unsafe_url("http://127.0.0.1:8080/test") is True

    def test_0_0_0_0(self):
        assert _is_unsafe_url("http://0.0.0.0/") is True

    def test_ipv6_loopback(self):
        assert _is_unsafe_url("http://[::1]/") is True

    def test_10_x_private(self):
        assert _is_unsafe_url("http://10.0.0.1/api") is True

    def test_192_168_private(self):
        assert _is_unsafe_url("http://192.168.1.100/api") is True

    def test_172_16_private(self):
        assert _is_unsafe_url("http://172.16.0.1/api") is True

    def test_172_31_private(self):
        assert _is_unsafe_url("http://172.31.255.255/") is True

    def test_172_15_not_private(self):
        assert _is_unsafe_url("http://172.15.0.1/") is False

    def test_172_32_not_private(self):
        assert _is_unsafe_url("http://172.32.0.1/") is False

    def test_link_local(self):
        assert _is_unsafe_url("http://169.254.169.254/metadata") is True

    def test_cloud_metadata(self):
        assert _is_unsafe_url("http://metadata.google.internal/") is True

    def test_public_url_safe(self):
        assert _is_unsafe_url("https://api.example.com/v1") is False

    def test_invalid_url_not_parseable(self):
        # urlparse treats malformed strings as having no hostname → not matched as private IP
        assert _is_unsafe_url("not a url at all ://") is False

    def test_ipv6_ula_unsafe(self):
        assert _is_unsafe_url("http://[fd12::1]/api") is True

    def test_ipv6_link_local_unsafe(self):
        assert _is_unsafe_url("http://[fe80::1]/api") is True


# ── _has_path_traversal ──


class TestHasPathTraversal:
    def test_dotdot(self):
        assert _has_path_traversal("../../etc/passwd") is True

    def test_absolute_unix(self):
        assert _has_path_traversal("/etc/passwd") is True

    def test_absolute_backslash(self):
        assert _has_path_traversal("\\windows\\system32") is True

    def test_windows_drive(self):
        assert _has_path_traversal("C:\\Users\\admin") is True

    def test_safe_relative(self):
        assert _has_path_traversal("data/file.txt") is False

    def test_safe_filename(self):
        assert _has_path_traversal("report.pdf") is False


# ── parameter_validation_hook ──


class TestParameterValidationHook:
    def _event(self, tool_input: dict) -> HookEvent:
        return HookEvent(
            event_type="pre_tool_use",
            tool_name="some_tool",
            tool_input=tool_input,
        )

    def test_safe_input_allow(self):
        result = parameter_validation_hook(self._event({"name": "test"}))
        assert result.action == "allow"

    def test_url_ssrf_block(self):
        result = parameter_validation_hook(self._event({"url": "http://127.0.0.1/admin"}))
        assert result.action == "block"
        assert "安全检查" in result.message

    def test_target_url_ssrf_block(self):
        result = parameter_validation_hook(self._event({"target_url": "http://10.0.0.5/api"}))
        assert result.action == "block"

    def test_api_url_ssrf_block(self):
        result = parameter_validation_hook(self._event({"api_url": "http://192.168.1.1/"}))
        assert result.action == "block"

    def test_safe_url_allow(self):
        result = parameter_validation_hook(self._event({"url": "https://example.com"}))
        assert result.action == "allow"

    def test_path_traversal_file_id(self):
        result = parameter_validation_hook(self._event({"file_id": "../../etc/passwd"}))
        assert result.action == "block"
        assert "路径" in result.message

    def test_path_traversal_file_path(self):
        result = parameter_validation_hook(self._event({"file_path": "/etc/shadow"}))
        assert result.action == "block"

    def test_path_traversal_filename(self):
        result = parameter_validation_hook(self._event({"filename": "C:\\secret"}))
        assert result.action == "block"

    def test_safe_path_allow(self):
        result = parameter_validation_hook(self._event({"file_id": "uploads/doc.pdf"}))
        assert result.action == "allow"

    def test_value_over_limit(self):
        result = parameter_validation_hook(self._event({"value": "200000000"}))
        assert result.action == "block"
        assert "1 亿" in result.message

    def test_amount_over_limit(self):
        result = parameter_validation_hook(self._event({"amount": -100000001}))
        assert result.action == "block"

    def test_value_within_limit(self):
        result = parameter_validation_hook(self._event({"value": "99999999"}))
        assert result.action == "allow"

    def test_non_numeric_value_skip(self):
        result = parameter_validation_hook(self._event({"value": "hello"}))
        assert result.action == "allow"

    def test_empty_url_skip(self):
        result = parameter_validation_hook(self._event({"url": ""}))
        assert result.action == "allow"


# ── sensitive_data_hook ──


class TestSensitiveDataHook:
    def _event(self, output: str) -> HookEvent:
        return HookEvent(
            event_type="post_tool_use",
            tool_name="some_tool",
            tool_input={},
            tool_output=output,
        )

    def test_no_output_allow(self):
        result = sensitive_data_hook(self._event(""))
        assert result.action == "allow"

    def test_clean_output_allow(self):
        result = sensitive_data_hook(self._event("Total: 1500 CNY"))
        assert result.action == "allow"

    def test_id_card_detected(self):
        result = sensitive_data_hook(self._event("身份证: 110101199001011234"))
        assert result.action == "allow"  # Only logs, doesn't block

    def test_phone_detected(self):
        result = sensitive_data_hook(self._event("手机: 13812345678"))
        assert result.action == "allow"

    def test_bank_card_detected(self):
        result = sensitive_data_hook(self._event("卡号: 6222021234567890123"))
        assert result.action == "allow"


# ── A6: data_lock_hook ──


class TestDataLockHook:
    """Tests for A6 DataLock hook integration."""

    @staticmethod
    def _event(tool_input: dict) -> HookEvent:
        return HookEvent(
            event_type="pre_tool_use",
            session_id="s1",
            user_id="U1",
            tool_name="update_form_field",
            tool_input=tool_input,
        )

    def test_no_registry_allows(self):
        """Without DataLockRegistry injected, always allow."""
        from core.context import RequestContext, current_request
        ctx = RequestContext(data_lock=None)
        tok = current_request.set(ctx)
        try:
            result = data_lock_hook(self._event({"field_id": "salary", "value": "100"}))
            assert result.action == "allow"
        finally:
            current_request.reset(tok)

    def test_readonly_field_blocked(self):
        """Readonly locked field is blocked."""
        from core.context import RequestContext, current_request
        from core.data_lock import DataLockRegistry, DataLock, LockLevel

        registry = DataLockRegistry()
        registry.register(DataLock(key="salary", level=LockLevel.READONLY, reason="薪资不可改"))
        ctx = RequestContext(data_lock=registry)
        tok = current_request.set(ctx)
        try:
            result = data_lock_hook(self._event({"field_id": "salary", "value": "999999"}))
            assert result.action == "block"
            assert "salary" in result.message
        finally:
            current_request.reset(tok)

    def test_audit_field_allowed(self):
        """Audit locked field is allowed (logged only)."""
        from core.context import RequestContext, current_request
        from core.data_lock import DataLockRegistry, DataLock, LockLevel

        registry = DataLockRegistry()
        registry.register(DataLock(key="department", level=LockLevel.AUDIT, reason="审计"))
        ctx = RequestContext(data_lock=registry)
        tok = current_request.set(ctx)
        try:
            result = data_lock_hook(self._event({"field_id": "department", "value": "Engineering"}))
            assert result.action == "allow"
        finally:
            current_request.reset(tok)

    def test_unlocked_field_allowed(self):
        """Unlocked field is always allowed."""
        from core.context import RequestContext, current_request
        from core.data_lock import DataLockRegistry

        registry = DataLockRegistry()
        ctx = RequestContext(data_lock=registry)
        tok = current_request.set(ctx)
        try:
            result = data_lock_hook(self._event({"field_id": "email", "value": "a@b.com"}))
            assert result.action == "allow"
        finally:
            current_request.reset(tok)

    def test_key_param_checked(self):
        """Also checks 'key' parameter (not just field_id)."""
        from core.context import RequestContext, current_request
        from core.data_lock import DataLockRegistry, DataLock, LockLevel

        registry = DataLockRegistry()
        registry.register(DataLock(key="config_key", level=LockLevel.READONLY, reason="locked"))
        ctx = RequestContext(data_lock=registry)
        tok = current_request.set(ctx)
        try:
            result = data_lock_hook(self._event({"key": "config_key", "value": "new"}))
            assert result.action == "block"
        finally:
            current_request.reset(tok)
