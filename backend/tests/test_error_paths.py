"""
Error-path tests for A2 MCP and A9 Webhook coverage gaps.

Covers:
1. HttpMCPProvider: invalid JSON body, malformed base_url, timeout edge cases, idempotent close
2. MCP tool exception propagation: provider raises → tool returns error dict
3. WebhookStore file I/O errors: corrupted JSON, permission errors, empty files
4. WebhookDispatcher edge cases: non-serializable data, retry counts, HMAC edge cases, status codes
5. ScheduleStore file I/O errors: corrupted JSON, permission errors, empty files
6. Webhook route input validation: invalid URLs, bad events, dispatcher exceptions
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import asyncio
import hashlib
import hmac as hmac_mod
import json
import stat
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from core.context import RequestContext, current_request
from core.scheduler import ScheduleStore, ScheduledTask
from core.webhook import WebhookConfig, WebhookDispatcher, WebhookStore
from tools.mcp.defaults import DefaultMCPProvider
from tools.mcp.http_provider import HttpMCPProvider
from tools.mcp.mcp_tools import (
    _get_provider,
    get_business_rules,
    get_candidate_types,
    get_form_schema,
    get_protected_values,
    query_data,
    submit_form_data,
)


# ── Fixtures ──


@pytest.fixture(autouse=True)
def _reset_mcp_context():
    """Reset RequestContext before each test."""
    ctx = RequestContext(mcp_provider=None)
    token = current_request.set(ctx)
    yield
    current_request.reset(token)


# ═══════════════════════════════════════════════════════════════════
# 1. HttpMCPProvider Error Paths
# ═══════════════════════════════════════════════════════════════════


class TestHttpMCPProviderInvalidJSON:
    """Server returns 200 but body is not valid JSON (e.g. HTML error page)."""

    @pytest.mark.asyncio
    async def test_get_200_with_html_body(self):
        """GET returns 200 but body is HTML -- should return error dict, not crash."""
        provider = HttpMCPProvider(base_url="http://test.local/api")
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.side_effect = json.JSONDecodeError("msg", "doc", 0)

        with patch.object(
            provider._client, "get", new_callable=AsyncMock, return_value=mock_resp
        ):
            result = await provider.get_form_schema("test")
            assert "error" in result
            assert "path" in result

    @pytest.mark.asyncio
    async def test_get_200_with_plain_text_body(self):
        """GET returns 200 but body is plain text, not JSON."""
        provider = HttpMCPProvider(base_url="http://test.local/api")
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.side_effect = ValueError("No JSON object could be decoded")

        with patch.object(
            provider._client, "get", new_callable=AsyncMock, return_value=mock_resp
        ):
            result = await provider.get_business_rules("test")
            assert "error" in result
            assert "path" in result
            assert result["path"] == "/rules/test"

    @pytest.mark.asyncio
    async def test_post_200_with_html_body(self):
        """POST returns 200 but body is HTML -- should return error dict."""
        provider = HttpMCPProvider(base_url="http://test.local/api")
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.side_effect = json.JSONDecodeError("msg", "doc", 0)

        with patch.object(
            provider._client, "post", new_callable=AsyncMock, return_value=mock_resp
        ):
            result = await provider.submit_form_data("leave", {"days": 1})
            assert "error" in result
            assert result["path"] == "/forms/leave/submit"

    @pytest.mark.asyncio
    async def test_post_200_with_plain_text_body(self):
        """POST returns 200 but body is plain text."""
        provider = HttpMCPProvider(base_url="http://test.local/api")
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.side_effect = ValueError("No JSON")

        with patch.object(
            provider._client, "post", new_callable=AsyncMock, return_value=mock_resp
        ):
            result = await provider.query_data("history", {"limit": 10})
            assert "error" in result
            assert result["path"] == "/query/history"


class TestHttpMCPProviderMalformedBaseUrl:
    """base_url with double slashes, query params, fragments."""

    def test_double_trailing_slashes_all_stripped(self):
        """rstrip('/') removes ALL trailing slashes."""
        provider = HttpMCPProvider(base_url="http://test.local/api//")
        assert provider.base_url == "http://test.local/api"

    def test_multiple_trailing_slashes(self):
        provider = HttpMCPProvider(base_url="http://test.local/api///")
        # rstrip("/") removes all trailing slashes
        assert provider.base_url == "http://test.local/api"

    def test_base_url_with_query_params(self):
        """base_url containing query params -- stored as-is (minus trailing slash)."""
        provider = HttpMCPProvider(base_url="http://test.local/api?key=val")
        assert provider.base_url == "http://test.local/api?key=val"

    def test_base_url_with_fragment(self):
        """base_url containing fragment -- stored as-is."""
        provider = HttpMCPProvider(base_url="http://test.local/api#section")
        assert provider.base_url == "http://test.local/api#section"

    def test_base_url_with_port(self):
        provider = HttpMCPProvider(base_url="http://test.local:9090/api/")
        assert provider.base_url == "http://test.local:9090/api"


class TestHttpMCPProviderTimeoutEdgeCases:
    """Timeout edge cases: zero and negative values."""

    def test_timeout_zero_creates_client(self):
        """timeout_s=0 should not crash on construction."""
        provider = HttpMCPProvider(base_url="http://test.local/api", timeout_s=0)
        assert provider._client is not None

    def test_timeout_negative_creates_client(self):
        """timeout_s=-1 should not crash on construction (httpx handles validation)."""
        provider = HttpMCPProvider(base_url="http://test.local/api", timeout_s=-1)
        assert provider._client is not None

    def test_timeout_very_small_creates_client(self):
        """Very small positive timeout creates client."""
        provider = HttpMCPProvider(base_url="http://test.local/api", timeout_s=0.001)
        assert provider._client is not None


class TestHttpMCPProviderCloseIdempotent:
    """close() when client is already closed should be idempotent."""

    @pytest.mark.asyncio
    async def test_close_twice_no_error(self):
        """Calling close() twice should not raise."""
        provider = HttpMCPProvider(base_url="http://test.local/api")
        await provider.close()
        await provider.close()  # second close should not raise

    @pytest.mark.asyncio
    async def test_close_with_mock_client_already_closed(self):
        """When underlying client is already closed, close() should still work."""
        provider = HttpMCPProvider(base_url="http://test.local/api")
        provider._client = AsyncMock()
        # First close
        await provider.close()
        # Mark aclose to raise (simulating already closed)
        provider._client.aclose.side_effect = RuntimeError("already closed")
        # Should propagate the error (no special handling in close())
        with pytest.raises(RuntimeError, match="already closed"):
            await provider.close()


# ═══════════════════════════════════════════════════════════════════
# 2. MCP Tool Exception Propagation
# ═══════════════════════════════════════════════════════════════════


class _RaisingProvider:
    """Provider that raises RuntimeError on every method."""

    async def get_form_schema(self, form_type: str) -> dict:
        raise RuntimeError("provider exploded")

    async def get_business_rules(self, rule_type: str) -> dict:
        raise RuntimeError("provider exploded")

    async def get_candidate_types(self, category: str) -> dict:
        raise RuntimeError("provider exploded")

    async def get_protected_values(self, context: str) -> dict:
        raise RuntimeError("provider exploded")

    async def submit_form_data(self, form_type: str, data: dict) -> dict:
        raise RuntimeError("provider exploded")

    async def query_data(self, query_type: str, params: dict) -> dict:
        raise RuntimeError("provider exploded")


class TestMCPToolExceptionPropagation:
    """When provider raises an exception, the tool should propagate it
    (the tool functions themselves do NOT catch exceptions -- they are
    thin wrappers; the runtime catches them at the tool-execution level).
    """

    @pytest.fixture(autouse=True)
    def _set_raising_provider(self):
        self.provider = _RaisingProvider()
        ctx = RequestContext(mcp_provider=self.provider)
        current_request.set(ctx)

    @pytest.mark.asyncio
    async def test_get_form_schema_raises(self):
        with pytest.raises(RuntimeError, match="provider exploded"):
            await get_form_schema(form_type="test")

    @pytest.mark.asyncio
    async def test_get_business_rules_raises(self):
        with pytest.raises(RuntimeError, match="provider exploded"):
            await get_business_rules(rule_type="test")

    @pytest.mark.asyncio
    async def test_get_candidate_types_raises(self):
        with pytest.raises(RuntimeError, match="provider exploded"):
            await get_candidate_types(category="test")

    @pytest.mark.asyncio
    async def test_get_protected_values_raises(self):
        with pytest.raises(RuntimeError, match="provider exploded"):
            await get_protected_values(context="test")

    @pytest.mark.asyncio
    async def test_submit_form_data_raises(self):
        with pytest.raises(RuntimeError, match="provider exploded"):
            await submit_form_data(form_type="test", data={})

    @pytest.mark.asyncio
    async def test_query_data_raises(self):
        with pytest.raises(RuntimeError, match="provider exploded"):
            await query_data(query_type="test", params={})


class TestGetProviderContextVarNeverSet:
    """_get_provider() when ContextVar was never set returns DefaultMCPProvider."""

    def test_returns_default_provider(self):
        """ContextVar default is None => _get_provider returns DefaultMCPProvider."""
        provider = _get_provider()
        assert isinstance(provider, DefaultMCPProvider)

    def test_returns_default_after_reset(self):
        """After setting and resetting, _get_provider should return DefaultMCPProvider."""
        ctx = RequestContext(mcp_provider=MagicMock())
        token = current_request.set(ctx)
        current_request.reset(token)
        provider = _get_provider()
        assert isinstance(provider, DefaultMCPProvider)


# ═══════════════════════════════════════════════════════════════════
# 3. WebhookStore File I/O Errors
# ═══════════════════════════════════════════════════════════════════


class TestWebhookStoreCorruptedJSON:
    """get() with corrupted JSON file."""

    def test_get_corrupted_json_returns_none(self, tmp_path):
        store = WebhookStore(str(tmp_path))
        config_dir = tmp_path / "t1"
        config_dir.mkdir()
        config_file = config_dir / "config.json"
        config_file.write_text("this is not json {{{", encoding="utf-8")

        result = store.get("t1")
        assert result is None

    def test_get_partial_json_returns_none(self, tmp_path):
        store = WebhookStore(str(tmp_path))
        config_dir = tmp_path / "t1"
        config_dir.mkdir()
        config_file = config_dir / "config.json"
        config_file.write_text('{"url": "https://example.com"', encoding="utf-8")  # unclosed

        result = store.get("t1")
        assert result is None

    def test_get_empty_file_returns_none(self, tmp_path):
        """Empty file can't be parsed as JSON."""
        store = WebhookStore(str(tmp_path))
        config_dir = tmp_path / "t1"
        config_dir.mkdir()
        config_file = config_dir / "config.json"
        config_file.write_text("", encoding="utf-8")

        result = store.get("t1")
        assert result is None

    def test_get_json_missing_url_key_returns_none(self, tmp_path):
        """Valid JSON but missing required 'url' key."""
        store = WebhookStore(str(tmp_path))
        config_dir = tmp_path / "t1"
        config_dir.mkdir()
        config_file = config_dir / "config.json"
        config_file.write_text('{"secret": "abc"}', encoding="utf-8")

        result = store.get("t1")
        assert result is None


class TestWebhookStoreSaveErrors:
    """save() with permission/directory errors."""

    def test_save_to_readonly_directory(self, tmp_path):
        """save() to a read-only directory should raise."""
        readonly_dir = tmp_path / "readonly"
        readonly_dir.mkdir()
        os.chmod(str(readonly_dir), stat.S_IRUSR | stat.S_IXUSR)

        store = WebhookStore(str(readonly_dir))
        config = WebhookConfig(url="https://example.com")

        try:
            with pytest.raises((PermissionError, OSError)):
                store.save("t1", config)
        finally:
            # Restore permissions for cleanup
            os.chmod(str(readonly_dir), stat.S_IRWXU)


class TestWebhookStoreDeleteErrors:
    """delete() when file exists but can't be deleted."""

    def test_delete_readonly_file(self, tmp_path):
        """delete() on a read-only parent dir should raise."""
        store = WebhookStore(str(tmp_path))
        config = WebhookConfig(url="https://example.com")
        store.save("t1", config)

        # Make the parent directory read-only to prevent deletion
        tenant_dir = tmp_path / "t1"
        os.chmod(str(tenant_dir), stat.S_IRUSR | stat.S_IXUSR)

        try:
            with pytest.raises((PermissionError, OSError)):
                store.delete("t1")
        finally:
            os.chmod(str(tenant_dir), stat.S_IRWXU)


# ═══════════════════════════════════════════════════════════════════
# 4. WebhookDispatcher Edge Cases
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def _bypass_webhook_dns_resolve():
    """Bypass DNS rebinding check for webhook dispatch tests."""
    with patch("core.webhook._resolve_to_unsafe_ip", return_value=False):
        yield


class TestWebhookDispatcherNonSerializableData:
    """dispatch() with data containing non-serializable objects."""

    @pytest.mark.asyncio
    async def test_dispatch_with_datetime_in_data_raises(self, tmp_path):
        """datetime objects are not JSON-serializable by default.

        json.dumps happens before the retry loop's try/except, so the
        TypeError propagates up uncaught.
        """
        store = WebhookStore(str(tmp_path))
        store.save("t1", WebhookConfig(url="https://ok.com/wh", events=["test"]))
        dispatcher = WebhookDispatcher(store=store, max_retries=1)

        with pytest.raises(TypeError, match="not JSON serializable"):
            await dispatcher.dispatch("t1", "test", {"when": datetime(2026, 1, 1)})

    @pytest.mark.asyncio
    async def test_dispatch_with_custom_class_in_data_raises(self, tmp_path):
        """Custom class instances are not JSON-serializable.

        The TypeError from json.dumps propagates because it is outside
        the per-attempt try/except.
        """
        store = WebhookStore(str(tmp_path))
        store.save("t1", WebhookConfig(url="https://ok.com/wh", events=["test"]))
        dispatcher = WebhookDispatcher(store=store, max_retries=1)

        class Unserializable:
            pass

        with pytest.raises(TypeError, match="not JSON serializable"):
            await dispatcher.dispatch("t1", "test", {"obj": Unserializable()})


class TestWebhookDispatcherEmptyEvents:
    """dispatch() with config.events=[] (empty list) vs events=None behavior."""

    @pytest.mark.asyncio
    async def test_dispatch_with_empty_events_list_passes_filter(self, tmp_path):
        """Empty events list is falsy, so the filter check is skipped."""
        store = WebhookStore(str(tmp_path))
        store.save("t1", WebhookConfig(url="https://ok.com/wh", events=[]))
        dispatcher = WebhookDispatcher(store=store, max_retries=1)

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            # Empty events list is falsy, so event filtering is skipped => dispatch proceeds
            ok = await dispatcher.dispatch("t1", "any_event", {"k": "v"})
            assert ok is True


class TestWebhookDispatcherRetryEdgeCases:
    """Test max_retries=0 and max_retries=1."""

    @pytest.mark.asyncio
    async def test_max_retries_zero_no_attempts(self, tmp_path):
        """max_retries=0 means range(0) => zero iterations => no HTTP call."""
        store = WebhookStore(str(tmp_path))
        store.save("t1", WebhookConfig(url="https://fail.com", events=["test"]))
        dispatcher = WebhookDispatcher(store=store, max_retries=0)

        call_count = 0

        async def track_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            return mock_resp

        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post = track_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            ok = await dispatcher.dispatch("t1", "test", {})
            assert ok is False
            assert call_count == 0

    @pytest.mark.asyncio
    async def test_max_retries_one_single_attempt(self, tmp_path):
        """max_retries=1 means exactly one attempt, no retry."""
        store = WebhookStore(str(tmp_path))
        store.save("t1", WebhookConfig(url="https://fail.com", events=["test"]))
        dispatcher = WebhookDispatcher(store=store, max_retries=1)

        call_count = 0
        mock_resp = MagicMock()
        mock_resp.status_code = 500

        async def track_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return mock_resp

        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post = track_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            ok = await dispatcher.dispatch("t1", "test", {})
            assert ok is False
            assert call_count == 1

    @pytest.mark.asyncio
    async def test_max_retries_one_success_on_first(self, tmp_path):
        """max_retries=1, success on first attempt."""
        store = WebhookStore(str(tmp_path))
        store.save("t1", WebhookConfig(url="https://ok.com", events=["test"]))
        dispatcher = WebhookDispatcher(store=store, max_retries=1)

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            ok = await dispatcher.dispatch("t1", "test", {})
            assert ok is True


class TestWebhookDispatcherHMACEdgeCases:
    """HMAC signing with empty string secret and very long secret."""

    def _compute_hmac(self, payload: bytes, secret: str) -> str:
        return hmac_mod.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()

    @pytest.mark.asyncio
    async def test_hmac_empty_string_secret_no_signature(self, tmp_path):
        """Empty string secret => config.secret is falsy => no signature header."""
        store = WebhookStore(str(tmp_path))
        store.save("t1", WebhookConfig(url="https://ok.com", secret="", events=["test"]))
        dispatcher = WebhookDispatcher(store=store, max_retries=1)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        captured_headers = {}

        async def capture_post(url, content, headers):
            captured_headers.update(headers)
            return mock_resp

        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post = capture_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            ok = await dispatcher.dispatch("t1", "test", {"x": 1})
            assert ok is True
            # Empty string is falsy => no signature
            assert "X-Claw-Signature" not in captured_headers

    @pytest.mark.asyncio
    async def test_hmac_long_secret(self, tmp_path):
        """Very long secret (>1KB) should still produce valid HMAC."""
        long_secret = "A" * 2048
        store = WebhookStore(str(tmp_path))
        store.save("t1", WebhookConfig(url="https://ok.com", secret=long_secret, events=["test"]))
        dispatcher = WebhookDispatcher(store=store, max_retries=1)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        captured = {"headers": {}, "content": b""}

        async def capture_post(url, content, headers):
            captured["headers"] = dict(headers)
            captured["content"] = content
            return mock_resp

        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post = capture_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            ok = await dispatcher.dispatch("t1", "test", {"x": 1})
            assert ok is True
            assert "X-Claw-Signature" in captured["headers"]
            # Verify the HMAC is correct
            expected_sig = self._compute_hmac(captured["content"], long_secret)
            assert captured["headers"]["X-Claw-Signature"] == expected_sig


class TestWebhookDispatcherHTTPStatusCodes:
    """Various HTTP response codes: 1xx, 3xx redirects."""

    async def _dispatch_with_status(self, tmp_path, status_code):
        store = WebhookStore(str(tmp_path))
        store.save("t1", WebhookConfig(url="https://test.com", events=["test"]))
        dispatcher = WebhookDispatcher(store=store, max_retries=1)

        mock_resp = MagicMock()
        mock_resp.status_code = status_code

        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            return await dispatcher.dispatch("t1", "test", {})

    @pytest.mark.asyncio
    async def test_1xx_informational_not_2xx(self, tmp_path):
        """100 Continue is not a success (not in 200-299 range)."""
        ok = await self._dispatch_with_status(tmp_path, 100)
        assert ok is False

    @pytest.mark.asyncio
    async def test_3xx_redirect_not_2xx(self, tmp_path):
        """301 Redirect is not treated as success."""
        ok = await self._dispatch_with_status(tmp_path, 301)
        assert ok is False

    @pytest.mark.asyncio
    async def test_302_redirect_not_2xx(self, tmp_path):
        ok = await self._dispatch_with_status(tmp_path, 302)
        assert ok is False

    @pytest.mark.asyncio
    async def test_200_ok_success(self, tmp_path):
        ok = await self._dispatch_with_status(tmp_path, 200)
        assert ok is True

    @pytest.mark.asyncio
    async def test_201_created_success(self, tmp_path):
        ok = await self._dispatch_with_status(tmp_path, 201)
        assert ok is True

    @pytest.mark.asyncio
    async def test_299_edge_success(self, tmp_path):
        ok = await self._dispatch_with_status(tmp_path, 299)
        assert ok is True

    @pytest.mark.asyncio
    async def test_300_not_success(self, tmp_path):
        ok = await self._dispatch_with_status(tmp_path, 300)
        assert ok is False

    @pytest.mark.asyncio
    async def test_199_not_success(self, tmp_path):
        ok = await self._dispatch_with_status(tmp_path, 199)
        assert ok is False


# ═══════════════════════════════════════════════════════════════════
# 5. ScheduleStore File I/O Errors
# ═══════════════════════════════════════════════════════════════════


def _make_task(**overrides) -> ScheduledTask:
    """Helper to build a ScheduledTask with defaults."""
    defaults = {
        "id": "task-1",
        "name": "Test Task",
        "cron": "*/5 * * * *",
        "message": "hello",
        "user_id": "u1",
        "tenant_id": "t1",
    }
    defaults.update(overrides)
    return ScheduledTask(**defaults)


class TestScheduleStoreCorruptedJSON:
    """_load_tasks() with corrupted JSON file."""

    def test_corrupted_json_returns_empty_list(self, tmp_path):
        store = ScheduleStore(str(tmp_path))
        task_dir = tmp_path / "t1" / "u1"
        task_dir.mkdir(parents=True)
        tasks_file = task_dir / "tasks.json"
        tasks_file.write_text("NOT VALID JSON {{{{", encoding="utf-8")

        result = store.list_tasks("t1", "u1")
        assert result == []

    def test_partial_json_returns_empty_list(self, tmp_path):
        store = ScheduleStore(str(tmp_path))
        task_dir = tmp_path / "t1" / "u1"
        task_dir.mkdir(parents=True)
        tasks_file = task_dir / "tasks.json"
        tasks_file.write_text('[{"id": "task-1"', encoding="utf-8")  # unclosed

        result = store.list_tasks("t1", "u1")
        assert result == []

    def test_empty_file_returns_empty_list(self, tmp_path):
        store = ScheduleStore(str(tmp_path))
        task_dir = tmp_path / "t1" / "u1"
        task_dir.mkdir(parents=True)
        tasks_file = task_dir / "tasks.json"
        tasks_file.write_text("", encoding="utf-8")

        result = store.list_tasks("t1", "u1")
        assert result == []

    def test_json_with_invalid_task_data_returns_empty(self, tmp_path):
        """Valid JSON array but items missing required fields."""
        store = ScheduleStore(str(tmp_path))
        task_dir = tmp_path / "t1" / "u1"
        task_dir.mkdir(parents=True)
        tasks_file = task_dir / "tasks.json"
        tasks_file.write_text('[{"bad_field": 123}]', encoding="utf-8")

        result = store.list_tasks("t1", "u1")
        assert result == []

    def test_json_is_dict_not_list(self, tmp_path):
        """File contains a JSON object (dict) instead of array."""
        store = ScheduleStore(str(tmp_path))
        task_dir = tmp_path / "t1" / "u1"
        task_dir.mkdir(parents=True)
        tasks_file = task_dir / "tasks.json"
        tasks_file.write_text('{"id": "task-1"}', encoding="utf-8")

        result = store.list_tasks("t1", "u1")
        assert result == []


class TestScheduleStoreSaveErrors:
    """_save_tasks() with read-only directory."""

    def test_save_to_readonly_directory(self, tmp_path):
        readonly_dir = tmp_path / "readonly"
        readonly_dir.mkdir()
        os.chmod(str(readonly_dir), stat.S_IRUSR | stat.S_IXUSR)

        store = ScheduleStore(str(readonly_dir))
        task = _make_task()

        try:
            with pytest.raises((PermissionError, OSError)):
                store.add(task)
        finally:
            os.chmod(str(readonly_dir), stat.S_IRWXU)


# ═══════════════════════════════════════════════════════════════════
# 6. Webhook Route Input Validation
# ═══════════════════════════════════════════════════════════════════


def _clear_all_lru_caches():
    """Clear all lru_cache entries in dependencies module."""
    import dependencies
    for name in dir(dependencies):
        obj = getattr(dependencies, name)
        if hasattr(obj, "cache_clear"):
            obj.cache_clear()


class TestWebhookRouteInputValidation:
    """POST /api/webhooks with various invalid inputs."""

    @pytest.fixture()
    def client(self):
        _clear_all_lru_caches()
        from main import app
        from core.auth import AuthUser, get_current_user
        from tests.test_webhook_routes import FakeWebhookStore, FakeWebhookDispatcher

        store = FakeWebhookStore()
        dispatcher = FakeWebhookDispatcher(should_succeed=True)

        user = AuthUser(tenant_id="tenant-1", user_id="UA01")
        app.dependency_overrides[get_current_user] = lambda: user

        with (
            patch("api.webhook_routes.get_webhook_store", return_value=store),
            patch("api.webhook_routes.get_webhook_dispatcher", return_value=dispatcher),
        ):
            from fastapi.testclient import TestClient
            c = TestClient(app, raise_server_exceptions=False)
            yield c

        app.dependency_overrides.clear()
        _clear_all_lru_caches()

    def test_empty_string_url_rejected(self, client):
        """Empty URL is rejected (scheme validation)."""
        resp = client.post("/api/webhooks", json={"url": ""})
        assert resp.status_code == 400

    def test_invalid_url_format_rejected(self, client):
        """Invalid URL format is rejected (scheme validation)."""
        resp = client.post("/api/webhooks", json={"url": "not-a-url"})
        assert resp.status_code == 400

    def test_internal_ip_url_rejected(self, client):
        """Internal IP URL is rejected (SSRF protection)."""
        resp = client.post("/api/webhooks", json={"url": "http://192.168.1.1/hook"})
        assert resp.status_code == 400

    def test_events_with_none_values(self, client):
        """Events list with None values -- Pydantic may coerce or reject."""
        resp = client.post("/api/webhooks", json={
            "url": "https://example.com/wh",
            "events": [None, "task_completed", None],
        })
        # Pydantic list[str] validation: None is not a valid string
        assert resp.status_code == 422

    def test_events_with_integer_values(self, client):
        """Events list with integer values."""
        resp = client.post("/api/webhooks", json={
            "url": "https://example.com/wh",
            "events": [123, 456],
        })
        # Pydantic may coerce ints to strings or reject
        # In Pydantic v2, int is coerced to str by default in strict mode off
        if resp.status_code == 200:
            # Coercion happened
            events = resp.json()["config"]["events"]
            assert all(isinstance(e, str) for e in events)
        else:
            assert resp.status_code == 422

    def test_missing_url_field(self, client):
        """URL is required by the Pydantic model."""
        resp = client.post("/api/webhooks", json={"secret": "abc"})
        assert resp.status_code == 422


class TestWebhookRouteTestEndpointException:
    """POST /api/webhooks/test when dispatcher.dispatch() raises an exception."""

    def test_dispatcher_exception_returns_500(self):
        _clear_all_lru_caches()
        from main import app
        from core.auth import AuthUser, get_current_user

        user = AuthUser(tenant_id="tenant-1", user_id="UA01")
        app.dependency_overrides[get_current_user] = lambda: user

        # Create a dispatcher that raises on dispatch
        mock_dispatcher = MagicMock()
        mock_dispatcher.dispatch = AsyncMock(side_effect=RuntimeError("dispatch boom"))

        mock_store = MagicMock()

        with (
            patch("api.webhook_routes.get_webhook_store", return_value=mock_store),
            patch("api.webhook_routes.get_webhook_dispatcher", return_value=mock_dispatcher),
        ):
            from fastapi.testclient import TestClient
            c = TestClient(app, raise_server_exceptions=False)
            resp = c.post("/api/webhooks/test")
            # FastAPI returns 500 for unhandled exceptions
            assert resp.status_code == 500

        app.dependency_overrides.clear()
        _clear_all_lru_caches()
