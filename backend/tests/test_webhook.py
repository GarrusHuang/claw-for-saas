"""
A9: Webhook 测试 — WebhookConfig / WebhookStore / WebhookDispatcher。
"""

import asyncio
import json
import os
import time
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from core.webhook import WebhookConfig, WebhookStore, WebhookDispatcher


# ───── WebhookConfig ─────

class TestWebhookConfig:
    def test_defaults(self):
        c = WebhookConfig(url="https://example.com/hook")
        assert c.url == "https://example.com/hook"
        assert c.secret == ""
        assert c.events == ["task_completed", "task_failed"]
        assert c.enabled is True

    def test_to_dict(self):
        c = WebhookConfig(url="https://x.com/h", secret="s3cr3t", events=["test"], enabled=False)
        d = c.to_dict()
        assert d["url"] == "https://x.com/h"
        assert d["secret"] == "s3cr3t"
        assert d["events"] == ["test"]
        assert d["enabled"] is False

    def test_from_dict(self):
        data = {"url": "https://a.com", "secret": "abc", "events": ["e1"], "enabled": True}
        c = WebhookConfig.from_dict(data)
        assert c.url == "https://a.com"
        assert c.secret == "abc"

    def test_from_dict_defaults(self):
        c = WebhookConfig.from_dict({"url": "https://b.com"})
        assert c.secret == ""
        assert c.events == ["task_completed", "task_failed"]
        assert c.enabled is True

    def test_roundtrip(self):
        orig = WebhookConfig(url="https://r.com", secret="key", events=["a", "b"])
        restored = WebhookConfig.from_dict(orig.to_dict())
        assert restored.url == orig.url
        assert restored.secret == orig.secret
        assert restored.events == orig.events


# ───── WebhookStore ─────

class TestWebhookStore:
    def test_save_and_get(self, tmp_path):
        store = WebhookStore(str(tmp_path))
        config = WebhookConfig(url="https://x.com/wh", secret="s")
        store.save("t1", config)
        loaded = store.get("t1")
        assert loaded is not None
        assert loaded.url == "https://x.com/wh"
        assert loaded.secret == "s"

    def test_get_nonexistent(self, tmp_path):
        store = WebhookStore(str(tmp_path))
        assert store.get("nope") is None

    def test_delete(self, tmp_path):
        store = WebhookStore(str(tmp_path))
        config = WebhookConfig(url="https://d.com")
        store.save("t1", config)
        assert store.delete("t1") is True
        assert store.get("t1") is None

    def test_delete_nonexistent(self, tmp_path):
        store = WebhookStore(str(tmp_path))
        assert store.delete("nope") is False

    def test_overwrite(self, tmp_path):
        store = WebhookStore(str(tmp_path))
        store.save("t1", WebhookConfig(url="https://old.com"))
        store.save("t1", WebhookConfig(url="https://new.com"))
        loaded = store.get("t1")
        assert loaded.url == "https://new.com"


# ───── WebhookDispatcher ─────

@pytest.fixture(autouse=True)
def _bypass_dns_resolve():
    """Bypass DNS rebinding check in all webhook dispatch tests."""
    with patch("core.webhook._resolve_to_unsafe_ip", return_value=False):
        yield


class TestWebhookDispatcher:
    @pytest.mark.asyncio
    async def test_dispatch_success(self, tmp_path):
        store = WebhookStore(str(tmp_path))
        store.save("t1", WebhookConfig(url="https://ok.com/wh", events=["task_completed"]))
        dispatcher = WebhookDispatcher(store=store, timeout_s=5, max_retries=1)

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            ok = await dispatcher.dispatch("t1", "task_completed", {"k": "v"})
            assert ok is True
            mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatch_no_config(self, tmp_path):
        store = WebhookStore(str(tmp_path))
        dispatcher = WebhookDispatcher(store=store)
        ok = await dispatcher.dispatch("none", "test", {})
        assert ok is False

    @pytest.mark.asyncio
    async def test_dispatch_disabled(self, tmp_path):
        store = WebhookStore(str(tmp_path))
        store.save("t1", WebhookConfig(url="https://d.com", enabled=False))
        dispatcher = WebhookDispatcher(store=store)
        ok = await dispatcher.dispatch("t1", "test", {})
        assert ok is False

    @pytest.mark.asyncio
    async def test_dispatch_event_filter(self, tmp_path):
        store = WebhookStore(str(tmp_path))
        store.save("t1", WebhookConfig(url="https://f.com", events=["task_completed"]))
        dispatcher = WebhookDispatcher(store=store)
        ok = await dispatcher.dispatch("t1", "unsubscribed_event", {})
        assert ok is False

    @pytest.mark.asyncio
    async def test_dispatch_hmac_signature(self, tmp_path):
        store = WebhookStore(str(tmp_path))
        store.save("t1", WebhookConfig(url="https://s.com", secret="mysecret", events=["test"]))
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
            assert "X-Claw-Signature" in captured_headers

    @pytest.mark.asyncio
    async def test_dispatch_retry_on_failure(self, tmp_path):
        store = WebhookStore(str(tmp_path))
        store.save("t1", WebhookConfig(url="https://fail.com", events=["test"]))
        dispatcher = WebhookDispatcher(store=store, max_retries=2)

        call_count = 0
        mock_resp_fail = MagicMock()
        mock_resp_fail.status_code = 500
        mock_resp_ok = MagicMock()
        mock_resp_ok.status_code = 200

        async def post_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_resp_fail
            return mock_resp_ok

        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post = post_side_effect
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            with patch("asyncio.sleep", new_callable=AsyncMock):
                ok = await dispatcher.dispatch("t1", "test", {})
                assert ok is True
                assert call_count == 2

    @pytest.mark.asyncio
    async def test_dispatch_all_retries_exhausted(self, tmp_path):
        store = WebhookStore(str(tmp_path))
        store.save("t1", WebhookConfig(url="https://down.com", events=["test"]))
        dispatcher = WebhookDispatcher(store=store, max_retries=2)

        mock_resp = MagicMock()
        mock_resp.status_code = 500

        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            with patch("asyncio.sleep", new_callable=AsyncMock):
                ok = await dispatcher.dispatch("t1", "test", {})
                assert ok is False


class TestDNSRebindingProtection:
    """DNS rebinding 防护测试 — 不使用 autouse bypass。"""

    @pytest.mark.asyncio
    async def test_dispatch_blocks_private_ip_resolution(self, tmp_path):
        """Webhook URL 解析到内网 IP 时应被阻止。"""
        store = WebhookStore(str(tmp_path))
        store.save("t1", WebhookConfig(url="https://evil.com/hook", events=["test"]))
        dispatcher = WebhookDispatcher(store=store)

        # 模拟 DNS 解析到内网 IP
        with patch("core.webhook._resolve_to_unsafe_ip", return_value=True):
            ok = await dispatcher.dispatch("t1", "test", {"data": "x"})
            assert ok is False

    @pytest.mark.asyncio
    async def test_dispatch_allows_public_ip_resolution(self, tmp_path):
        """Webhook URL 解析到公网 IP 时应放行。"""
        store = WebhookStore(str(tmp_path))
        store.save("t1", WebhookConfig(url="https://public.com/hook", events=["test"]))
        dispatcher = WebhookDispatcher(store=store, max_retries=1)

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("core.webhook._resolve_to_unsafe_ip", return_value=False):
            with patch("httpx.AsyncClient") as MockClient:
                mock_client = AsyncMock()
                mock_client.post.return_value = mock_resp
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                MockClient.return_value = mock_client

                ok = await dispatcher.dispatch("t1", "test", {"data": "x"})
                assert ok is True
