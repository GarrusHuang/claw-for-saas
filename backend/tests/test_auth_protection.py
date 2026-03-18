"""
T3: Auth 保护 API 拒绝测试。

验证 auth_enabled=True 时，未携带 token 的请求被 401 拒绝。
"""
from __future__ import annotations

import os
import pytest
from unittest.mock import patch


@pytest.fixture
def auth_client():
    """创建启用认证的 TestClient。"""
    # 设置环境变量启用认证
    env_overrides = {
        "AUTH_ENABLED": "true",
        "AUTH_JWT_SECRET": "test-secret-for-auth-test",
        "AUTH_MODE": "jwt",
        "LLM_MODEL": "test-model",
    }
    with patch.dict(os.environ, env_overrides):
        # 清除 lru_cache 以使用新配置
        from dependencies import get_settings
        get_settings.cache_clear()

        from fastapi.testclient import TestClient
        from main import app
        client = TestClient(app, raise_server_exceptions=False)
        yield client

        get_settings.cache_clear()


class TestAuthProtection:
    """无 token 时 API 应返回 401。"""

    def test_session_list_requires_auth(self, auth_client):
        """GET /api/session/list 无 token → 401。"""
        resp = auth_client.get("/api/session/list")
        assert resp.status_code == 401

    def test_skills_requires_auth(self, auth_client):
        """GET /api/skills 无 token → 401。"""
        resp = auth_client.get("/api/skills")
        assert resp.status_code == 401

    def test_health_is_public(self, auth_client):
        """GET /api/health 不需要认证。"""
        resp = auth_client.get("/api/health")
        assert resp.status_code == 200

    def test_login_rate_limit(self, auth_client):
        """连续错误登录应触发限速 (账户级 5 次/5min)。"""
        from api.auth import _login_attempts
        _login_attempts.clear()

        got_429 = False
        # 发送 7 次错误登录 — 第 6 次应被限速
        for i in range(7):
            resp = auth_client.post("/api/auth/login", json={
                "username": "ratelimit_test",
                "password": "wrong",
                "tenant_id": "default",
            })
            if resp.status_code == 429:
                got_429 = True
                break

        assert got_429, "Expected 429 rate limit after 5+ failed login attempts"
