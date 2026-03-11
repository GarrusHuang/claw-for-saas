"""
Comprehensive tests for A9 Webhook API routes.

Tests all 4 endpoints in api/webhook_routes.py:
  GET    /api/webhooks       - get tenant webhook config
  POST   /api/webhooks       - register/update webhook
  DELETE /api/webhooks       - delete webhook
  POST   /api/webhooks/test  - send test webhook

Uses FastAPI TestClient with monkeypatched auth, webhook store, and dispatcher.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import dependencies
from core.auth import AuthUser, get_current_user
from core.webhook import WebhookConfig, WebhookStore


# ── Helpers ──


USER_A = AuthUser(tenant_id="tenant-1", user_id="UA01")
USER_B = AuthUser(tenant_id="tenant-2", user_id="UB02")


def _make_config(
    url: str = "https://example.com/webhook",
    secret: str = "s3cret",
    events: list[str] | None = None,
    enabled: bool = True,
) -> WebhookConfig:
    return WebhookConfig(
        url=url,
        secret=secret,
        events=events if events is not None else ["task_completed", "task_failed"],
        enabled=enabled,
    )


def _clear_all_lru_caches():
    for name in dir(dependencies):
        obj = getattr(dependencies, name)
        if hasattr(obj, "cache_clear"):
            obj.cache_clear()


class FakeWebhookStore:
    """In-memory webhook store keyed by tenant_id."""

    def __init__(self):
        self._configs: dict[str, WebhookConfig] = {}

    def get(self, tenant_id: str) -> WebhookConfig | None:
        return self._configs.get(tenant_id)

    def save(self, tenant_id: str, config: WebhookConfig) -> None:
        self._configs[tenant_id] = config

    def delete(self, tenant_id: str) -> bool:
        if tenant_id in self._configs:
            del self._configs[tenant_id]
            return True
        return False


class FakeWebhookDispatcher:
    """Controllable dispatcher for testing."""

    def __init__(self, should_succeed: bool = True):
        self.should_succeed = should_succeed
        self.dispatch_calls: list[dict] = []

    async def dispatch(self, tenant_id: str, event: str, data: dict) -> bool:
        self.dispatch_calls.append({
            "tenant_id": tenant_id,
            "event": event,
            "data": data,
        })
        return self.should_succeed


# ── Fixtures ──


@pytest.fixture()
def fake_store():
    return FakeWebhookStore()


@pytest.fixture()
def fake_dispatcher():
    return FakeWebhookDispatcher(should_succeed=True)


@pytest.fixture()
def client(fake_store, fake_dispatcher):
    """TestClient with patched auth (USER_A), webhook store, and dispatcher."""
    _clear_all_lru_caches()

    from main import app

    app.dependency_overrides[get_current_user] = lambda: USER_A

    with (
        patch("api.webhook_routes.get_webhook_store", return_value=fake_store),
        patch("api.webhook_routes.get_webhook_dispatcher", return_value=fake_dispatcher),
    ):
        c = TestClient(app, raise_server_exceptions=False)
        yield c

    app.dependency_overrides.clear()
    _clear_all_lru_caches()


# ═══════════════════════════════════════════════════════════
# 1. Get webhook — GET /api/webhooks
# ═══════════════════════════════════════════════════════════


class TestGetWebhook:
    def test_no_config_returns_none(self, client):
        resp = client.get("/api/webhooks")
        assert resp.status_code == 200
        data = resp.json()
        assert data["config"] is None

    def test_existing_config_returned(self, client, fake_store):
        config = _make_config(url="https://hooks.example.com/callback")
        fake_store.save("tenant-1", config)

        resp = client.get("/api/webhooks")
        assert resp.status_code == 200
        data = resp.json()
        assert data["config"] is not None
        assert data["config"]["url"] == "https://hooks.example.com/callback"
        assert data["config"]["secret"] == "s3cret"
        assert data["config"]["enabled"] is True

    def test_config_has_all_fields(self, client, fake_store):
        config = _make_config(
            url="https://example.com/wh",
            secret="key123",
            events=["task_completed", "task_failed", "custom_event"],
            enabled=True,
        )
        fake_store.save("tenant-1", config)

        resp = client.get("/api/webhooks")
        data = resp.json()["config"]
        assert "url" in data
        assert "secret" in data
        assert "events" in data
        assert "enabled" in data
        assert len(data["events"]) == 3

    def test_get_returns_tenant_specific_config(self):
        """Each tenant has its own isolated config."""
        _clear_all_lru_caches()
        from main import app

        store = FakeWebhookStore()
        dispatcher = FakeWebhookDispatcher()
        store.save("tenant-1", _make_config(url="https://a.example.com"))
        store.save("tenant-2", _make_config(url="https://b.example.com"))

        with (
            patch("api.webhook_routes.get_webhook_store", return_value=store),
            patch("api.webhook_routes.get_webhook_dispatcher", return_value=dispatcher),
        ):
            # Tenant A
            app.dependency_overrides[get_current_user] = lambda: USER_A
            c = TestClient(app, raise_server_exceptions=False)
            resp_a = c.get("/api/webhooks")
            assert resp_a.json()["config"]["url"] == "https://a.example.com"

            # Tenant B
            app.dependency_overrides[get_current_user] = lambda: USER_B
            resp_b = c.get("/api/webhooks")
            assert resp_b.json()["config"]["url"] == "https://b.example.com"

        app.dependency_overrides.clear()
        _clear_all_lru_caches()


# ═══════════════════════════════════════════════════════════
# 2. Register webhook — POST /api/webhooks
# ═══════════════════════════════════════════════════════════


class TestRegisterWebhook:
    def test_create_new(self, client, fake_store):
        payload = {
            "url": "https://myapp.com/webhook",
            "secret": "my-secret",
            "events": ["task_completed"],
            "enabled": True,
        }
        resp = client.post("/api/webhooks", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "saved"
        assert data["config"]["url"] == "https://myapp.com/webhook"
        assert data["config"]["secret"] == "my-secret"
        assert data["config"]["events"] == ["task_completed"]
        assert data["config"]["enabled"] is True

        # Verify it persisted in the store
        stored = fake_store.get("tenant-1")
        assert stored is not None
        assert stored.url == "https://myapp.com/webhook"

    def test_overwrite_existing(self, client, fake_store):
        # First registration
        fake_store.save("tenant-1", _make_config(url="https://old.example.com"))

        # Overwrite
        payload = {
            "url": "https://new.example.com/webhook",
            "secret": "new-secret",
        }
        resp = client.post("/api/webhooks", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["config"]["url"] == "https://new.example.com/webhook"
        assert data["config"]["secret"] == "new-secret"

        # Verify store was updated
        stored = fake_store.get("tenant-1")
        assert stored.url == "https://new.example.com/webhook"

    def test_default_events(self, client):
        payload = {"url": "https://example.com/wh"}
        resp = client.post("/api/webhooks", json=payload)
        assert resp.status_code == 200
        events = resp.json()["config"]["events"]
        assert events == ["task_completed", "task_failed"]

    def test_default_secret_empty(self, client):
        payload = {"url": "https://example.com/wh"}
        resp = client.post("/api/webhooks", json=payload)
        assert resp.status_code == 200
        assert resp.json()["config"]["secret"] == ""

    def test_default_enabled_true(self, client):
        payload = {"url": "https://example.com/wh"}
        resp = client.post("/api/webhooks", json=payload)
        assert resp.status_code == 200
        assert resp.json()["config"]["enabled"] is True

    def test_register_disabled(self, client):
        payload = {"url": "https://example.com/wh", "enabled": False}
        resp = client.post("/api/webhooks", json=payload)
        assert resp.status_code == 200
        assert resp.json()["config"]["enabled"] is False

    def test_register_custom_events(self, client):
        payload = {
            "url": "https://example.com/wh",
            "events": ["task_completed", "custom_event", "another_event"],
        }
        resp = client.post("/api/webhooks", json=payload)
        assert resp.status_code == 200
        events = resp.json()["config"]["events"]
        assert "custom_event" in events
        assert "another_event" in events
        assert len(events) == 3

    def test_register_missing_url_returns_422(self, client):
        resp = client.post("/api/webhooks", json={})
        assert resp.status_code == 422

    def test_register_empty_body_returns_422(self, client):
        resp = client.post("/api/webhooks", content=b"", headers={"content-type": "application/json"})
        assert resp.status_code == 422

    def test_register_and_get_roundtrip(self, client):
        payload = {
            "url": "https://round.example.com/hook",
            "secret": "rt-secret",
            "events": ["task_completed"],
        }
        post_resp = client.post("/api/webhooks", json=payload)
        assert post_resp.status_code == 200

        get_resp = client.get("/api/webhooks")
        assert get_resp.status_code == 200
        config = get_resp.json()["config"]
        assert config["url"] == "https://round.example.com/hook"
        assert config["secret"] == "rt-secret"
        assert config["events"] == ["task_completed"]

    def test_tenant_isolation_on_register(self):
        """Registering for tenant A does not affect tenant B."""
        _clear_all_lru_caches()
        from main import app

        store = FakeWebhookStore()
        dispatcher = FakeWebhookDispatcher()

        with (
            patch("api.webhook_routes.get_webhook_store", return_value=store),
            patch("api.webhook_routes.get_webhook_dispatcher", return_value=dispatcher),
        ):
            c = TestClient(app, raise_server_exceptions=False)

            # Tenant A registers
            app.dependency_overrides[get_current_user] = lambda: USER_A
            c.post("/api/webhooks", json={"url": "https://a.example.com"})

            # Tenant B registers
            app.dependency_overrides[get_current_user] = lambda: USER_B
            c.post("/api/webhooks", json={"url": "https://b.example.com"})

        assert store.get("tenant-1").url == "https://a.example.com"
        assert store.get("tenant-2").url == "https://b.example.com"

        app.dependency_overrides.clear()
        _clear_all_lru_caches()


# ═══════════════════════════════════════════════════════════
# 3. Delete webhook — DELETE /api/webhooks
# ═══════════════════════════════════════════════════════════


class TestDeleteWebhook:
    def test_delete_existing(self, client, fake_store):
        fake_store.save("tenant-1", _make_config())

        resp = client.delete("/api/webhooks")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "deleted"

        # Verify it's gone
        assert fake_store.get("tenant-1") is None

    def test_delete_nonexistent_returns_404(self, client):
        resp = client.delete("/api/webhooks")
        assert resp.status_code == 404
        assert "No webhook configured" in resp.json()["detail"]

    def test_delete_idempotent_second_call_404(self, client, fake_store):
        fake_store.save("tenant-1", _make_config())

        resp1 = client.delete("/api/webhooks")
        assert resp1.status_code == 200

        resp2 = client.delete("/api/webhooks")
        assert resp2.status_code == 404

    def test_delete_only_affects_own_tenant(self):
        _clear_all_lru_caches()
        from main import app

        store = FakeWebhookStore()
        dispatcher = FakeWebhookDispatcher()
        store.save("tenant-1", _make_config(url="https://a.example.com"))
        store.save("tenant-2", _make_config(url="https://b.example.com"))

        with (
            patch("api.webhook_routes.get_webhook_store", return_value=store),
            patch("api.webhook_routes.get_webhook_dispatcher", return_value=dispatcher),
        ):
            app.dependency_overrides[get_current_user] = lambda: USER_A
            c = TestClient(app, raise_server_exceptions=False)

            # Tenant A deletes their webhook
            resp = c.delete("/api/webhooks")
            assert resp.status_code == 200

        # Tenant B's webhook is unaffected
        assert store.get("tenant-2") is not None
        assert store.get("tenant-2").url == "https://b.example.com"

        app.dependency_overrides.clear()
        _clear_all_lru_caches()

    def test_delete_then_get_returns_none(self, client, fake_store):
        fake_store.save("tenant-1", _make_config())

        client.delete("/api/webhooks")

        resp = client.get("/api/webhooks")
        assert resp.status_code == 200
        assert resp.json()["config"] is None


# ═══════════════════════════════════════════════════════════
# 4. Test webhook — POST /api/webhooks/test
# ═══════════════════════════════════════════════════════════


class TestWebhookTest:
    def test_success(self, client, fake_dispatcher):
        fake_dispatcher.should_succeed = True

        resp = client.post("/api/webhooks/test")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "delivered"

    def test_failure(self, client, fake_dispatcher):
        fake_dispatcher.should_succeed = False

        resp = client.post("/api/webhooks/test")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "failed"
        assert "detail" in data

    def test_dispatch_called_with_correct_params(self, client, fake_dispatcher):
        fake_dispatcher.should_succeed = True

        client.post("/api/webhooks/test")

        assert len(fake_dispatcher.dispatch_calls) == 1
        call = fake_dispatcher.dispatch_calls[0]
        assert call["tenant_id"] == USER_A.tenant_id
        assert call["event"] == "test"
        assert "message" in call["data"]
        assert "test webhook" in call["data"]["message"].lower()

    def test_dispatch_uses_authenticated_tenant(self):
        """Test webhook uses the authenticated user's tenant_id."""
        _clear_all_lru_caches()
        from main import app

        dispatcher = FakeWebhookDispatcher(should_succeed=True)
        store = FakeWebhookStore()

        app.dependency_overrides[get_current_user] = lambda: USER_B

        with (
            patch("api.webhook_routes.get_webhook_store", return_value=store),
            patch("api.webhook_routes.get_webhook_dispatcher", return_value=dispatcher),
        ):
            c = TestClient(app, raise_server_exceptions=False)
            c.post("/api/webhooks/test")

        assert len(dispatcher.dispatch_calls) == 1
        assert dispatcher.dispatch_calls[0]["tenant_id"] == USER_B.tenant_id

        app.dependency_overrides.clear()
        _clear_all_lru_caches()

    def test_test_does_not_require_existing_config(self, client, fake_dispatcher):
        """The test endpoint dispatches even if no webhook config exists in store.

        Whether it succeeds depends on the dispatcher (which checks its own store).
        """
        fake_dispatcher.should_succeed = False

        resp = client.post("/api/webhooks/test")
        # The route just relays the dispatcher's return value
        assert resp.status_code == 200
        assert resp.json()["status"] == "failed"


# ═══════════════════════════════════════════════════════════
# 5. Auth required on all endpoints
# ═══════════════════════════════════════════════════════════


class TestAuthRequired:
    def test_all_endpoints_reject_without_auth(self):
        """When auth raises 401, all webhook endpoints reject."""
        _clear_all_lru_caches()
        from main import app

        def require_auth():
            from fastapi import HTTPException
            raise HTTPException(status_code=401, detail="Unauthorized")

        app.dependency_overrides[get_current_user] = require_auth

        c = TestClient(app, raise_server_exceptions=False)

        endpoints = [
            ("GET", "/api/webhooks"),
            ("POST", "/api/webhooks"),
            ("DELETE", "/api/webhooks"),
            ("POST", "/api/webhooks/test"),
        ]

        for method, path in endpoints:
            if method == "GET":
                resp = c.get(path)
            elif method == "POST":
                resp = c.post(path, json={"url": "https://example.com"})
            elif method == "DELETE":
                resp = c.delete(path)
            else:
                raise ValueError(f"Unhandled method: {method}")

            assert resp.status_code == 401, (
                f"{method} {path} should require auth, got {resp.status_code}"
            )

        app.dependency_overrides.clear()
        _clear_all_lru_caches()

    def test_get_uses_authenticated_tenant(self, fake_store):
        """GET returns config for the authenticated user's tenant, not a hardcoded one."""
        _clear_all_lru_caches()
        from main import app

        fake_store.save("custom-tenant", _make_config(url="https://custom.example.com"))

        custom_user = AuthUser(tenant_id="custom-tenant", user_id="CU01")
        app.dependency_overrides[get_current_user] = lambda: custom_user

        with (
            patch("api.webhook_routes.get_webhook_store", return_value=fake_store),
            patch("api.webhook_routes.get_webhook_dispatcher", return_value=FakeWebhookDispatcher()),
        ):
            c = TestClient(app, raise_server_exceptions=False)
            resp = c.get("/api/webhooks")
            assert resp.status_code == 200
            assert resp.json()["config"]["url"] == "https://custom.example.com"

        app.dependency_overrides.clear()
        _clear_all_lru_caches()

    def test_register_saves_to_authenticated_tenant(self, fake_store):
        """POST saves config under the authenticated user's tenant_id."""
        _clear_all_lru_caches()
        from main import app

        custom_user = AuthUser(tenant_id="save-tenant", user_id="SU01")
        app.dependency_overrides[get_current_user] = lambda: custom_user

        with (
            patch("api.webhook_routes.get_webhook_store", return_value=fake_store),
            patch("api.webhook_routes.get_webhook_dispatcher", return_value=FakeWebhookDispatcher()),
        ):
            c = TestClient(app, raise_server_exceptions=False)
            resp = c.post("/api/webhooks", json={"url": "https://saved.example.com"})
            assert resp.status_code == 200

        stored = fake_store.get("save-tenant")
        assert stored is not None
        assert stored.url == "https://saved.example.com"

        app.dependency_overrides.clear()
        _clear_all_lru_caches()

    def test_delete_removes_authenticated_tenant_only(self, fake_store):
        """DELETE only removes the authenticated user's tenant config."""
        _clear_all_lru_caches()
        from main import app

        fake_store.save("del-tenant", _make_config(url="https://del.example.com"))
        fake_store.save("other-tenant", _make_config(url="https://other.example.com"))

        custom_user = AuthUser(tenant_id="del-tenant", user_id="DU01")
        app.dependency_overrides[get_current_user] = lambda: custom_user

        with (
            patch("api.webhook_routes.get_webhook_store", return_value=fake_store),
            patch("api.webhook_routes.get_webhook_dispatcher", return_value=FakeWebhookDispatcher()),
        ):
            c = TestClient(app, raise_server_exceptions=False)
            resp = c.delete("/api/webhooks")
            assert resp.status_code == 200

        assert fake_store.get("del-tenant") is None
        assert fake_store.get("other-tenant") is not None

        app.dependency_overrides.clear()
        _clear_all_lru_caches()


# ═══════════════════════════════════════════════════════════
# 6. Webhook config data integrity
# ═══════════════════════════════════════════════════════════


class TestWebhookConfigIntegrity:
    """Verify that WebhookConfig data flows correctly through the API."""

    def test_to_dict_format(self, client, fake_store):
        config = WebhookConfig(
            url="https://example.com/wh",
            secret="sec",
            events=["task_completed"],
            enabled=True,
        )
        fake_store.save("tenant-1", config)

        resp = client.get("/api/webhooks")
        data = resp.json()["config"]
        assert isinstance(data, dict)
        assert set(data.keys()) == {"url", "secret", "events", "enabled"}

    def test_events_list_preserved(self, client):
        """Events list is stored and returned exactly as provided."""
        events = ["task_completed", "task_failed", "schedule_paused", "custom.event"]
        payload = {"url": "https://example.com", "events": events}
        client.post("/api/webhooks", json=payload)

        resp = client.get("/api/webhooks")
        assert resp.json()["config"]["events"] == events

    def test_empty_events_list(self, client):
        payload = {"url": "https://example.com", "events": []}
        resp = client.post("/api/webhooks", json=payload)
        assert resp.status_code == 200
        assert resp.json()["config"]["events"] == []

    def test_url_preserved_exactly(self, client):
        url = "https://hooks.myapp.io:8443/v2/callbacks?token=abc123&type=claw"
        payload = {"url": url}
        resp = client.post("/api/webhooks", json=payload)
        assert resp.status_code == 200
        assert resp.json()["config"]["url"] == url

    def test_secret_preserved_exactly(self, client):
        secret = "whsec_a1b2c3d4e5f6"
        payload = {"url": "https://example.com", "secret": secret}
        resp = client.post("/api/webhooks", json=payload)
        assert resp.status_code == 200
        assert resp.json()["config"]["secret"] == secret

    def test_overwrite_preserves_no_old_data(self, client, fake_store):
        """Overwriting a webhook fully replaces the old config, not merging."""
        client.post("/api/webhooks", json={
            "url": "https://old.example.com",
            "secret": "old-secret",
            "events": ["task_completed", "task_failed", "extra_event"],
        })

        client.post("/api/webhooks", json={
            "url": "https://new.example.com",
        })

        resp = client.get("/api/webhooks")
        config = resp.json()["config"]
        assert config["url"] == "https://new.example.com"
        # The new registration used defaults, so secret should be empty
        assert config["secret"] == ""
        # Events should be the default, not the old ones
        assert config["events"] == ["task_completed", "task_failed"]
