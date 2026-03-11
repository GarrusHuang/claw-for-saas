"""
Comprehensive API route tests for admin, auth, plugin, skill, and SSE modules.

Uses FastAPI TestClient with monkeypatched dependency functions to isolate
tests.  Auth is disabled by default (auth_enabled=False), so every route
receives a default AuthUser(tenant_id="default", user_id="U001").
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock, patch, AsyncMock

import pytest
from fastapi.testclient import TestClient

import dependencies
import api.file_routes as file_routes_mod
import api.session_routes as session_routes_mod
import api.correction_routes as correction_routes_mod
import api.memory_routes as memory_routes_mod
import api.plugin_routes as plugin_routes_mod
from agent.session import SessionManager
from memory.markdown_store import MarkdownMemoryStore
from services.file_service import FileService
from services.database import DatabaseService
from agent.hook_rules import HookRuleEngine
from skills.loader import SkillLoader
from core.plugin import PluginRegistry, PluginContext
from core.tool_registry import ToolRegistry


def _clear_all_lru_caches():
    """Clear every lru_cache in the dependencies module."""
    for name in dir(dependencies):
        obj = getattr(dependencies, name)
        if hasattr(obj, "cache_clear"):
            obj.cache_clear()


@pytest.fixture(autouse=True)
def isolated_app(tmp_path):
    """
    Provide a TestClient backed by temporary directories for every test.

    Patches the cached dependency factory functions so that each test gets
    fresh, isolated service instances rooted under ``tmp_path``.
    """
    _clear_all_lru_caches()

    session_dir = tmp_path / "sessions"
    memory_dir = tmp_path / "memory"
    files_dir = tmp_path / "files"
    hook_rules_dir = tmp_path / "hook_rules"
    skills_dir = tmp_path / "skills"
    db_path = tmp_path / "test.db"

    for d in (session_dir, memory_dir, files_dir, hook_rules_dir, skills_dir):
        d.mkdir()

    sm = SessionManager(base_dir=str(session_dir))
    ms = MarkdownMemoryStore(base_dir=str(memory_dir))
    fs = FileService(base_dir=str(files_dir))
    hre = HookRuleEngine(str(hook_rules_dir))
    sl = SkillLoader(skills_dir=str(skills_dir))
    db = DatabaseService(db_path=str(db_path))
    db.ensure_default_tenant_and_admin(tenant_id="default", admin_user_id="U001")

    pr = PluginRegistry()

    from main import app

    with (
        patch.object(dependencies, "get_session_manager", return_value=sm),
        patch.object(dependencies, "get_memory_store", return_value=ms),
        patch.object(dependencies, "get_file_service", return_value=fs),
        patch.object(dependencies, "get_hook_rule_engine", return_value=hre),
        patch.object(dependencies, "get_skill_loader", return_value=sl),
        patch.object(dependencies, "get_database", return_value=db),
        patch.object(dependencies, "get_plugin_registry", return_value=pr),
        patch.object(dependencies, "get_prompt_builder", return_value=MagicMock()),
        # Route modules that import at module top level
        patch.object(file_routes_mod, "get_file_service", return_value=fs),
        patch.object(session_routes_mod, "get_session_manager", return_value=sm),
        patch.object(correction_routes_mod, "get_memory_store", return_value=ms),
        patch.object(memory_routes_mod, "get_session_manager", return_value=sm),
        patch.object(memory_routes_mod, "get_memory_store", return_value=ms),
        patch.object(plugin_routes_mod, "get_plugin_registry", return_value=pr),
        patch.object(plugin_routes_mod, "get_skill_loader", return_value=sl),
        patch.object(plugin_routes_mod, "get_settings", return_value=MagicMock(plugins_dir="plugins")),
        patch.object(plugin_routes_mod, "get_prompt_builder", return_value=MagicMock()),
    ):
        client = TestClient(app, raise_server_exceptions=False)
        # Expose db for tests that need direct DB access
        client._test_db = db
        client._test_skill_loader = sl
        client._test_plugin_registry = pr
        yield client

    _clear_all_lru_caches()
    app.dependency_overrides.clear()


# ═══════════════════════════════════════════════════════════
# Admin Routes — /api/admin/*
# ═══════════════════════════════════════════════════════════


class TestAdminTenants:
    """Tests for tenant CRUD under /api/admin/tenants."""

    def test_list_tenants_returns_default(self, isolated_app):
        resp = isolated_app.get("/api/admin/tenants")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        # default tenant created by ensure_default_tenant_and_admin
        assert any(t["tenant_id"] == "default" for t in data)

    def test_create_tenant(self, isolated_app):
        resp = isolated_app.post("/api/admin/tenants", json={
            "tenant_id": "T100",
            "name": "Test Tenant",
            "max_users": 50,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["tenant_id"] == "T100"
        assert data["name"] == "Test Tenant"
        assert data["max_users"] == 50

    def test_create_duplicate_tenant_returns_409(self, isolated_app):
        isolated_app.post("/api/admin/tenants", json={
            "tenant_id": "TDUP",
            "name": "First",
        })
        resp = isolated_app.post("/api/admin/tenants", json={
            "tenant_id": "TDUP",
            "name": "Second",
        })
        assert resp.status_code == 409

    def test_get_tenant_by_id(self, isolated_app):
        isolated_app.post("/api/admin/tenants", json={
            "tenant_id": "TGET",
            "name": "Get Me",
        })
        resp = isolated_app.get("/api/admin/tenants/TGET")
        assert resp.status_code == 200
        data = resp.json()
        assert data["tenant_id"] == "TGET"
        assert data["name"] == "Get Me"

    def test_get_tenant_not_found_returns_404(self, isolated_app):
        resp = isolated_app.get("/api/admin/tenants/nonexistent")
        assert resp.status_code == 404

    def test_update_tenant(self, isolated_app):
        isolated_app.post("/api/admin/tenants", json={
            "tenant_id": "TUPD",
            "name": "Before",
        })
        resp = isolated_app.put("/api/admin/tenants/TUPD", json={
            "name": "After",
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        # Verify update
        get_resp = isolated_app.get("/api/admin/tenants/TUPD")
        assert get_resp.json()["name"] == "After"

    def test_update_nonexistent_tenant_returns_404(self, isolated_app):
        resp = isolated_app.put("/api/admin/tenants/nope", json={"name": "X"})
        assert resp.status_code == 404

    def test_delete_tenant(self, isolated_app):
        isolated_app.post("/api/admin/tenants", json={
            "tenant_id": "TDEL",
            "name": "Delete Me",
        })
        resp = isolated_app.delete("/api/admin/tenants/TDEL")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        # Verify gone
        assert isolated_app.get("/api/admin/tenants/TDEL").status_code == 404

    def test_delete_nonexistent_tenant_returns_404(self, isolated_app):
        resp = isolated_app.delete("/api/admin/tenants/nope")
        assert resp.status_code == 404


class TestAdminUsers:
    """Tests for user CRUD under /api/admin/tenants/{tenant_id}/users."""

    def test_list_users_empty(self, isolated_app):
        isolated_app.post("/api/admin/tenants", json={
            "tenant_id": "TUSERS",
            "name": "Users Test",
        })
        resp = isolated_app.get("/api/admin/tenants/TUSERS/users")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_create_user(self, isolated_app):
        isolated_app.post("/api/admin/tenants", json={
            "tenant_id": "TUCR",
            "name": "Users",
        })
        resp = isolated_app.post("/api/admin/tenants/TUCR/users", json={
            "user_id": "U100",
            "username": "alice",
            "password": "secret123",
            "roles": ["user"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == "U100"
        assert data["username"] == "alice"
        assert data["roles"] == ["user"]

    def test_create_user_tenant_not_found(self, isolated_app):
        resp = isolated_app.post("/api/admin/tenants/nonexistent/users", json={
            "user_id": "U100",
            "username": "alice",
            "password": "secret123",
        })
        assert resp.status_code == 404

    def test_create_duplicate_user_returns_409(self, isolated_app):
        isolated_app.post("/api/admin/tenants", json={
            "tenant_id": "TUDUP",
            "name": "Dup Users",
        })
        isolated_app.post("/api/admin/tenants/TUDUP/users", json={
            "user_id": "UDUP",
            "username": "bob",
            "password": "pass",
        })
        resp = isolated_app.post("/api/admin/tenants/TUDUP/users", json={
            "user_id": "UDUP",
            "username": "bob2",
            "password": "pass",
        })
        assert resp.status_code == 409

    def test_get_user_by_id(self, isolated_app):
        isolated_app.post("/api/admin/tenants", json={
            "tenant_id": "TUGET",
            "name": "Get User",
        })
        isolated_app.post("/api/admin/tenants/TUGET/users", json={
            "user_id": "UGET",
            "username": "carol",
            "password": "pass",
            "roles": ["admin"],
        })
        resp = isolated_app.get("/api/admin/tenants/TUGET/users/UGET")
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == "UGET"
        assert data["username"] == "carol"

    def test_get_user_not_found_returns_404(self, isolated_app):
        resp = isolated_app.get("/api/admin/tenants/default/users/nonexistent")
        assert resp.status_code == 404

    def test_update_user(self, isolated_app):
        isolated_app.post("/api/admin/tenants", json={
            "tenant_id": "TUUPD",
            "name": "Upd User",
        })
        isolated_app.post("/api/admin/tenants/TUUPD/users", json={
            "user_id": "UUPD",
            "username": "dave",
            "password": "pass",
            "roles": [],
        })
        resp = isolated_app.put("/api/admin/tenants/TUUPD/users/UUPD", json={
            "roles": ["admin", "user"],
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_update_nonexistent_user_returns_404(self, isolated_app):
        resp = isolated_app.put("/api/admin/tenants/default/users/nope", json={
            "status": "disabled",
        })
        assert resp.status_code == 404

    def test_delete_user(self, isolated_app):
        isolated_app.post("/api/admin/tenants", json={
            "tenant_id": "TUDEL",
            "name": "Del User",
        })
        isolated_app.post("/api/admin/tenants/TUDEL/users", json={
            "user_id": "UDEL",
            "username": "eve",
            "password": "pass",
        })
        resp = isolated_app.delete("/api/admin/tenants/TUDEL/users/UDEL")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        # Verify gone
        assert isolated_app.get("/api/admin/tenants/TUDEL/users/UDEL").status_code == 404

    def test_delete_nonexistent_user_returns_404(self, isolated_app):
        resp = isolated_app.delete("/api/admin/tenants/default/users/nope")
        assert resp.status_code == 404


class TestAdminApiKeys:
    """Tests for API key CRUD under /api/admin/tenants/{tenant_id}/api-keys."""

    def test_list_api_keys_empty(self, isolated_app):
        resp = isolated_app.get("/api/admin/tenants/default/api-keys")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_create_api_key(self, isolated_app):
        resp = isolated_app.post("/api/admin/tenants/default/api-keys", json={
            "description": "Test key",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "key" in data
        assert "key_id" in data
        assert data["tenant_id"] == "default"
        assert data["description"] == "Test key"
        assert "warning" in data

    def test_create_api_key_tenant_not_found(self, isolated_app):
        resp = isolated_app.post("/api/admin/tenants/nonexistent/api-keys", json={
            "description": "Test",
        })
        assert resp.status_code == 404

    def test_list_api_keys_after_create(self, isolated_app):
        isolated_app.post("/api/admin/tenants/default/api-keys", json={
            "description": "Listed key",
        })
        resp = isolated_app.get("/api/admin/tenants/default/api-keys")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["description"] == "Listed key"

    def test_revoke_api_key(self, isolated_app):
        create_resp = isolated_app.post("/api/admin/tenants/default/api-keys", json={
            "description": "Revoke me",
        })
        key_id = create_resp.json()["key_id"]
        resp = isolated_app.post(f"/api/admin/tenants/default/api-keys/{key_id}/revoke")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_revoke_nonexistent_api_key_returns_404(self, isolated_app):
        resp = isolated_app.post("/api/admin/tenants/default/api-keys/nope/revoke")
        assert resp.status_code == 404

    def test_delete_api_key(self, isolated_app):
        create_resp = isolated_app.post("/api/admin/tenants/default/api-keys", json={
            "description": "Delete me",
        })
        key_id = create_resp.json()["key_id"]
        resp = isolated_app.delete(f"/api/admin/tenants/default/api-keys/{key_id}")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_delete_nonexistent_api_key_returns_404(self, isolated_app):
        resp = isolated_app.delete("/api/admin/tenants/default/api-keys/nope")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════
# Auth Routes — /api/auth/*
# ═══════════════════════════════════════════════════════════


class TestAuthLogin:
    """Tests for POST /api/auth/login."""

    def _patch_settings(self, **overrides):
        """Return a context manager that patches config.settings for auth tests."""
        import config
        defaults = {
            "auth_enabled": True,
            "auth_jwt_secret": "test-secret-key-123",
            "auth_jwt_algorithm": "HS256",
            "auth_session_expire_s": 3600,
            "auth_default_tenant_id": "default",
            "auth_default_user_id": "U001",
            "auth_mode": "jwt",
            "app_debug": False,
        }
        defaults.update(overrides)
        mock_settings = MagicMock(**defaults)
        return patch.object(config, "settings", mock_settings)

    def test_login_auth_disabled_returns_400(self, isolated_app):
        """When auth_enabled=False, login endpoint returns 400."""
        resp = isolated_app.post("/api/auth/login", json={
            "username": "admin",
            "password": "pass",
            "tenant_id": "default",
        })
        assert resp.status_code == 400
        assert "not enabled" in resp.json()["detail"].lower()

    def test_login_valid_credentials(self, isolated_app):
        """Login with valid credentials when auth is enabled."""
        db = isolated_app._test_db
        db.create_tenant("AUTH_T", "Auth Tenant")
        db.create_user("AUTH_T", "UAUTH", "testuser", "testpass", roles=["user"])

        with self._patch_settings():
            resp = isolated_app.post("/api/auth/login", json={
                "username": "testuser",
                "password": "testpass",
                "tenant_id": "AUTH_T",
            })
            assert resp.status_code == 200
            data = resp.json()
            assert "token" in data
            assert data["token_type"] == "bearer"
            assert data["user_id"] == "UAUTH"
            assert data["tenant_id"] == "AUTH_T"

    def test_login_invalid_credentials(self, isolated_app):
        """Login with wrong password returns 401."""
        db = isolated_app._test_db
        db.create_tenant("AUTH_T2", "Auth Tenant 2")
        db.create_user("AUTH_T2", "UAUTH2", "testuser2", "correctpass", roles=[])

        with self._patch_settings():
            resp = isolated_app.post("/api/auth/login", json={
                "username": "testuser2",
                "password": "wrongpass",
                "tenant_id": "AUTH_T2",
            })
            assert resp.status_code == 401

    def test_login_missing_fields_returns_422(self, isolated_app):
        """Login without required fields returns 422."""
        resp = isolated_app.post("/api/auth/login", json={})
        assert resp.status_code == 422


class TestAuthMe:
    """Tests for GET /api/auth/me."""

    def _patch_settings(self, **overrides):
        import config
        defaults = {
            "auth_enabled": True,
            "auth_jwt_secret": "test-secret-key-456",
            "auth_jwt_algorithm": "HS256",
            "auth_session_expire_s": 3600,
            "auth_default_tenant_id": "default",
            "auth_default_user_id": "U001",
            "auth_mode": "jwt",
            "app_debug": False,
        }
        defaults.update(overrides)
        mock_settings = MagicMock(**defaults)
        return patch.object(config, "settings", mock_settings)

    def test_me_returns_default_user_when_auth_disabled(self, isolated_app):
        """When auth_enabled=False, /me returns default dev user."""
        resp = isolated_app.get("/api/auth/me")
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == "U001"
        assert data["tenant_id"] == "default"

    def test_me_with_valid_jwt(self, isolated_app):
        """With auth enabled and valid JWT, /me returns user info."""
        from core.auth import issue_session_token
        secret = "test-secret-key-456"
        token = issue_session_token(
            user_id="UJWT",
            tenant_id="TJWT",
            roles=["admin"],
            secret=secret,
            algorithm="HS256",
            expires_in=3600,
        )

        with self._patch_settings(auth_jwt_secret=secret):
            resp = isolated_app.get("/api/auth/me", headers={
                "Authorization": f"Bearer {token}",
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["user_id"] == "UJWT"
            assert data["tenant_id"] == "TJWT"
            assert data["roles"] == ["admin"]

    def test_me_without_token_auth_enabled_returns_401(self, isolated_app):
        """When auth is enabled but no token provided, returns 401."""
        with self._patch_settings():
            resp = isolated_app.get("/api/auth/me")
            assert resp.status_code == 401


class TestAuthRefresh:
    """Tests for POST /api/auth/refresh."""

    def _patch_settings(self, **overrides):
        import config
        defaults = {
            "auth_enabled": True,
            "auth_jwt_secret": "test-secret-refresh",
            "auth_jwt_algorithm": "HS256",
            "auth_session_expire_s": 3600,
            "auth_default_tenant_id": "default",
            "auth_default_user_id": "U001",
            "auth_mode": "jwt",
            "app_debug": False,
        }
        defaults.update(overrides)
        mock_settings = MagicMock(**defaults)
        return patch.object(config, "settings", mock_settings)

    def test_refresh_auth_disabled_returns_400(self, isolated_app):
        """When auth_enabled=False, refresh returns 400."""
        resp = isolated_app.post("/api/auth/refresh")
        assert resp.status_code == 400

    def test_refresh_with_valid_token(self, isolated_app):
        """Refresh with valid JWT returns new token."""
        from core.auth import issue_session_token
        secret = "test-secret-refresh"
        token = issue_session_token(
            user_id="UREF",
            tenant_id="TREF",
            roles=["user"],
            secret=secret,
            expires_in=3600,
        )

        with self._patch_settings(auth_jwt_secret=secret):
            resp = isolated_app.post("/api/auth/refresh", headers={
                "Authorization": f"Bearer {token}",
            })
            assert resp.status_code == 200
            data = resp.json()
            assert "token" in data
            assert data["token_type"] == "bearer"


class TestAuthDevToken:
    """Tests for POST /api/auth/dev-token."""

    def _patch_settings(self, **overrides):
        import config
        defaults = {
            "auth_enabled": True,
            "auth_jwt_secret": "dev-secret-123",
            "auth_jwt_algorithm": "HS256",
            "auth_session_expire_s": 3600,
            "auth_default_tenant_id": "default",
            "auth_default_user_id": "U001",
            "auth_mode": "jwt",
            "app_debug": False,
        }
        defaults.update(overrides)
        mock_settings = MagicMock(**defaults)
        return patch.object(config, "settings", mock_settings)

    def test_dev_token_auth_disabled_returns_400(self, isolated_app):
        """When auth_enabled=False, dev-token returns 400."""
        resp = isolated_app.post("/api/auth/dev-token", json={
            "user_id": "U001",
            "tenant_id": "default",
            "roles": [],
            "expires_in": 3600,
        })
        assert resp.status_code == 400

    def test_dev_token_not_debug_returns_403(self, isolated_app):
        """When auth_enabled=True but app_debug=False, returns 403."""
        with self._patch_settings(app_debug=False):
            resp = isolated_app.post("/api/auth/dev-token", json={
                "user_id": "U001",
                "tenant_id": "default",
                "roles": [],
                "expires_in": 3600,
            })
            assert resp.status_code == 403

    def test_dev_token_success(self, isolated_app):
        """When auth_enabled=True and app_debug=True, returns token."""
        with self._patch_settings(app_debug=True):
            resp = isolated_app.post("/api/auth/dev-token", json={
                "user_id": "UDEV",
                "tenant_id": "TDEV",
                "roles": ["admin"],
                "expires_in": 1800,
            })
            assert resp.status_code == 200
            data = resp.json()
            assert "token" in data
            assert data["expires_in"] == 1800


# ═══════════════════════════════════════════════════════════
# Plugin Routes — /api/plugins/*
# ═══════════════════════════════════════════════════════════


class TestPluginRoutes:
    """Tests for plugin management endpoints."""

    def test_list_plugins_empty(self, isolated_app):
        resp = isolated_app.get("/api/plugins")
        assert resp.status_code == 200
        data = resp.json()
        assert "plugins" in data
        assert "count" in data
        assert data["count"] == 0
        assert data["plugins"] == []

    def test_load_plugin_file_not_found(self, isolated_app):
        resp = isolated_app.post("/api/plugins/load", json={
            "name": "nonexistent_plugin",
        })
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_unload_plugin_not_found(self, isolated_app):
        resp = isolated_app.post("/api/plugins/nonexistent/unload")
        assert resp.status_code == 404

    def test_load_plugin_already_loaded_returns_409(self, isolated_app):
        """If plugin already loaded, returns 409."""
        pr = isolated_app._test_plugin_registry
        # Simulate a loaded plugin
        from core.plugin import PluginInfo
        pr._plugins = {"fake_plugin": PluginInfo(name="fake_plugin", version="1.0", description="Fake")}

        resp = isolated_app.post("/api/plugins/load", json={
            "name": "fake_plugin",
        })
        assert resp.status_code == 409
        assert "already loaded" in resp.json()["detail"].lower()

    def test_unload_loaded_plugin(self, isolated_app):
        """Unload a plugin that was previously loaded."""
        pr = isolated_app._test_plugin_registry
        from core.plugin import PluginInfo
        pr._plugins = {"my_plugin": PluginInfo(name="my_plugin", version="1.0", description="My")}

        resp = isolated_app.post("/api/plugins/my_plugin/unload")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "my_plugin"
        assert "unloaded" in data["message"].lower()

    def test_list_plugins_after_manual_add(self, isolated_app):
        """List plugins returns loaded plugins."""
        pr = isolated_app._test_plugin_registry
        from core.plugin import PluginInfo
        pr._plugins = {
            "p1": PluginInfo(name="p1", version="1.0", description="Plugin 1"),
            "p2": PluginInfo(name="p2", version="2.0", description="Plugin 2"),
        }

        resp = isolated_app.get("/api/plugins")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        names = [p["name"] for p in data["plugins"]]
        assert "p1" in names
        assert "p2" in names


# ═══════════════════════════════════════════════════════════
# Skill Routes — /api/skills/* (expanded coverage)
# ═══════════════════════════════════════════════════════════


class TestSkillRoutesExpanded:
    """Expanded tests for Skill CRUD + import."""

    def test_list_skills_empty(self, isolated_app):
        resp = isolated_app.get("/api/skills")
        assert resp.status_code == 200
        data = resp.json()
        assert data["skills"] == []
        assert data["total"] == 0

    def test_create_skill_valid(self, isolated_app):
        body_text = "This is a test skill body with enough content. " * 20
        resp = isolated_app.post("/api/skills", json={
            "name": "test-skill",
            "description": "A test skill for testing",
            "type": "domain",
            "version": "1.0",
            "body": body_text,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True

    def test_create_skill_missing_name_returns_422(self, isolated_app):
        resp = isolated_app.post("/api/skills", json={
            "description": "No name",
        })
        assert resp.status_code == 422

    def test_create_skill_duplicate_name(self, isolated_app):
        body_text = "Enough content for validation to pass. " * 20
        isolated_app.post("/api/skills", json={
            "name": "dup-skill",
            "description": "First",
            "type": "domain",
            "version": "1.0",
            "body": body_text,
        })
        resp = isolated_app.post("/api/skills", json={
            "name": "dup-skill",
            "description": "Second",
            "type": "domain",
            "version": "1.0",
            "body": body_text,
        })
        # Should fail — duplicate name creates file conflict
        assert resp.status_code == 400

    def test_get_skill_detail_existing(self, isolated_app):
        body_text = "Detail skill body content. " * 20
        isolated_app.post("/api/skills", json={
            "name": "detail-skill",
            "description": "Get detail",
            "type": "domain",
            "version": "1.0",
            "body": body_text,
        })
        resp = isolated_app.get("/api/skills/detail-skill")
        assert resp.status_code == 200
        data = resp.json()
        assert "metadata" in data
        assert "body" in data

    def test_get_skill_detail_not_found(self, isolated_app):
        resp = isolated_app.get("/api/skills/nonexistent-skill")
        assert resp.status_code == 404

    def test_update_skill_valid(self, isolated_app):
        body_text = "Original body content for testing. " * 20
        isolated_app.post("/api/skills", json={
            "name": "upd-skill",
            "description": "Original",
            "type": "domain",
            "version": "1.0",
            "body": body_text,
        })
        updated_body = "Updated body content for testing. " * 20
        resp = isolated_app.put("/api/skills/upd-skill", json={
            "name": "upd-skill",
            "description": "Updated",
            "type": "domain",
            "version": "2.0",
            "body": updated_body,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True

    def test_update_nonexistent_skill(self, isolated_app):
        resp = isolated_app.put("/api/skills/nonexistent", json={
            "name": "nonexistent",
            "description": "Does not exist",
            "type": "domain",
            "version": "1.0",
            "body": "Some body",
        })
        assert resp.status_code == 400

    def test_delete_skill_existing(self, isolated_app):
        body_text = "Delete me body content. " * 20
        isolated_app.post("/api/skills", json={
            "name": "del-skill",
            "description": "Delete me",
            "type": "domain",
            "version": "1.0",
            "body": body_text,
        })
        resp = isolated_app.delete("/api/skills/del-skill")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True

    def test_delete_skill_not_found(self, isolated_app):
        resp = isolated_app.delete("/api/skills/nonexistent")
        assert resp.status_code == 400

    def test_import_skill_with_content(self, isolated_app):
        content = """---
name: imported-skill
description: An imported skill
type: domain
version: "1.0"
---

This is the imported skill body content. """ + "Extra words here. " * 20

        resp = isolated_app.post("/api/skills/import", json={
            "content": content,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True

    def test_import_skill_no_content_or_url(self, isolated_app):
        resp = isolated_app.post("/api/skills/import", json={})
        assert resp.status_code == 400
        data = resp.json()
        assert data["ok"] is False

    def test_import_skill_invalid_url(self, isolated_app):
        resp = isolated_app.post("/api/skills/import", json={
            "url": "http://invalid.localhost.test/skill.md",
        })
        assert resp.status_code == 400


# ═══════════════════════════════════════════════════════════
# SSE — event_bus_to_sse
# ═══════════════════════════════════════════════════════════


class TestSSEEventBusToSSE:
    """Tests for the event_bus_to_sse generator function."""

    def test_event_bus_to_sse_basic(self):
        """Test that events are correctly converted to SSE dict format."""
        from api.sse import event_bus_to_sse
        from core.event_bus import EventBus

        bus = EventBus("test-trace-1")

        async def run():
            # Emit events: text_delta first, then pipeline_complete (auto-closes)
            bus.emit("text_delta", {"delta": "hello"})
            bus.emit("pipeline_complete", {"status": "ok"})

            results = []
            async for item in event_bus_to_sse(bus):
                results.append(item)
            return results

        loop = asyncio.new_event_loop()
        try:
            results = loop.run_until_complete(run())
        finally:
            loop.close()

        assert len(results) == 2

        # Check first event
        assert results[0]["event"] == "text_delta"
        parsed = json.loads(results[0]["data"])
        assert parsed["delta"] == "hello"

        # Check second event
        assert results[1]["event"] == "pipeline_complete"
        parsed = json.loads(results[1]["data"])
        assert parsed["status"] == "ok"

    def test_sse_format_has_event_and_data_keys(self):
        """Verify each yielded dict has 'event' and 'data' keys."""
        from api.sse import event_bus_to_sse
        from core.event_bus import EventBus

        bus = EventBus("test-trace-2")

        async def run():
            bus.emit("agent_progress", {"iteration": 1})
            bus.emit("pipeline_complete", {"status": "done"})

            results = []
            async for item in event_bus_to_sse(bus):
                results.append(item)
            return results

        loop = asyncio.new_event_loop()
        try:
            results = loop.run_until_complete(run())
        finally:
            loop.close()

        for item in results:
            assert "event" in item, "SSE dict must have 'event' key"
            assert "data" in item, "SSE dict must have 'data' key"
            # data must be a JSON string
            json.loads(item["data"])

    def test_sse_unicode_content(self):
        """Verify Chinese/unicode content is preserved (ensure_ascii=False)."""
        from api.sse import event_bus_to_sse
        from core.event_bus import EventBus

        bus = EventBus("test-trace-3")

        async def run():
            bus.emit("text_delta", {"delta": "你好世界"})
            bus.emit("pipeline_complete", {"status": "done"})

            results = []
            async for item in event_bus_to_sse(bus):
                results.append(item)
            return results

        loop = asyncio.new_event_loop()
        try:
            results = loop.run_until_complete(run())
        finally:
            loop.close()

        # First event is text_delta with unicode
        assert len(results) >= 1
        parsed = json.loads(results[0]["data"])
        assert parsed["delta"] == "你好世界"

    def test_sse_empty_data_defaults(self):
        """Events with no extra data still produce valid JSON in data field."""
        from api.sse import event_bus_to_sse
        from core.event_bus import EventBus

        bus = EventBus("test-trace-4")

        async def run():
            bus.emit("pipeline_complete")  # no data dict

            results = []
            async for item in event_bus_to_sse(bus):
                results.append(item)
            return results

        loop = asyncio.new_event_loop()
        try:
            results = loop.run_until_complete(run())
        finally:
            loop.close()

        assert len(results) == 1
        assert results[0]["event"] == "pipeline_complete"
        # data should be valid JSON
        parsed = json.loads(results[0]["data"])
        assert isinstance(parsed, dict)

    def test_sse_multiple_events_ordering(self):
        """Events are yielded in emission order."""
        from api.sse import event_bus_to_sse
        from core.event_bus import EventBus

        bus = EventBus("test-trace-5")

        async def run():
            bus.emit("text_delta", {"delta": "a"})
            bus.emit("text_delta", {"delta": "b"})
            bus.emit("text_delta", {"delta": "c"})
            bus.emit("pipeline_complete", {"status": "done"})

            results = []
            async for item in event_bus_to_sse(bus):
                results.append(item)
            return results

        loop = asyncio.new_event_loop()
        try:
            results = loop.run_until_complete(run())
        finally:
            loop.close()

        assert len(results) == 4
        deltas = [json.loads(r["data"])["delta"] for r in results[:3]]
        assert deltas == ["a", "b", "c"]
