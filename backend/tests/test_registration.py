"""
4.6 用户注册流程 — 测试套件。

覆盖:
- invite_code CRUD (创建/消费/过期/用完/撤销)
- POST /api/auth/register 成功/失败
- admin invite-code 端点
"""

from __future__ import annotations

import time
import pytest
from unittest.mock import patch, MagicMock

from services.database import DatabaseService, InviteCodeRecord


# ── Fixtures ──

@pytest.fixture
def db(tmp_path):
    """创建临时数据库。"""
    db_path = str(tmp_path / "test.db")
    service = DatabaseService(db_path)
    service.create_tenant("T001", "Test Tenant")
    return service


# ── invite_code CRUD Tests ──


class TestInviteCodeCRUD:

    def test_create_invite_code(self, db):
        """创建邀请码。"""
        code = db.create_invite_code("T001", roles=["user"], max_uses=5, created_by="U001")
        assert code.startswith("inv_")

    def test_consume_invite_code_success(self, db):
        """成功消费邀请码。"""
        code = db.create_invite_code("T001", roles=["user", "viewer"], max_uses=3, created_by="U001")
        result = db.consume_invite_code(code)
        assert result is not None
        tenant_id, roles = result
        assert tenant_id == "T001"
        assert roles == ["user", "viewer"]

    def test_consume_invite_code_exhausted(self, db):
        """邀请码用完。"""
        code = db.create_invite_code("T001", max_uses=1, created_by="U001")
        result1 = db.consume_invite_code(code)
        assert result1 is not None
        result2 = db.consume_invite_code(code)
        assert result2 is None

    def test_consume_invite_code_expired(self, db):
        """邀请码过期。"""
        code = db.create_invite_code(
            "T001", max_uses=10, expires_at=time.time() - 100, created_by="U001",
        )
        result = db.consume_invite_code(code)
        assert result is None

    def test_consume_invite_code_revoked(self, db):
        """邀请码已撤销。"""
        code = db.create_invite_code("T001", max_uses=10, created_by="U001")
        db.revoke_invite_code(code)
        result = db.consume_invite_code(code)
        assert result is None

    def test_consume_invite_code_not_found(self, db):
        """不存在的邀请码。"""
        result = db.consume_invite_code("inv_nonexistent")
        assert result is None

    def test_list_invite_codes(self, db):
        """列出邀请码。"""
        db.create_invite_code("T001", roles=["admin"], max_uses=1, created_by="U001")
        db.create_invite_code("T001", roles=["user"], max_uses=5, created_by="U001")
        codes = db.list_invite_codes("T001")
        assert len(codes) == 2
        assert all(isinstance(c, InviteCodeRecord) for c in codes)

    def test_revoke_invite_code(self, db):
        """撤销邀请码。"""
        code = db.create_invite_code("T001", created_by="U001")
        ok = db.revoke_invite_code(code)
        assert ok is True
        codes = db.list_invite_codes("T001")
        revoked = [c for c in codes if c.code == code]
        assert revoked[0].status == "revoked"

    def test_revoke_nonexistent(self, db):
        """撤销不存在的邀请码。"""
        ok = db.revoke_invite_code("inv_nonexistent")
        assert ok is False

    def test_consume_multi_use(self, db):
        """多次使用邀请码。"""
        code = db.create_invite_code("T001", max_uses=3, created_by="U001")
        for _ in range(3):
            result = db.consume_invite_code(code)
            assert result is not None
        # 第 4 次失败
        result = db.consume_invite_code(code)
        assert result is None


# ── Register endpoint tests ──


class TestRegisterEndpoint:

    @pytest.fixture
    def client(self, db):
        """创建测试客户端。"""
        from fastapi.testclient import TestClient
        from main import app

        with patch("dependencies.get_database", return_value=db):
            with patch("config.settings") as mock_settings:
                mock_settings.auth_enabled = True
                mock_settings.auth_jwt_secret = "test-secret-key-12345678"
                mock_settings.auth_jwt_algorithm = "HS256"
                mock_settings.auth_session_expire_s = 3600
                mock_settings.app_debug = False
                yield TestClient(app)

    def test_register_success(self, db, client):
        """注册成功返回 JWT。"""
        code = db.create_invite_code("T001", roles=["user"], max_uses=1, created_by="U001")
        resp = client.post("/api/auth/register", json={
            "invite_code": code,
            "username": "newuser",
            "password": "password123",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "token" in data
        assert data["tenant_id"] == "T001"
        assert data["user_id"].startswith("U")

    def test_register_invalid_invite_code(self, db, client):
        """无效邀请码返回 400。"""
        resp = client.post("/api/auth/register", json={
            "invite_code": "inv_invalid",
            "username": "newuser",
            "password": "password123",
        })
        assert resp.status_code == 400

    def test_register_duplicate_username(self, db, client):
        """用户名重复返回 409。"""
        code1 = db.create_invite_code("T001", max_uses=2, created_by="U001")
        # 先注册一个
        resp1 = client.post("/api/auth/register", json={
            "invite_code": code1,
            "username": "dupuser",
            "password": "password123",
        })
        assert resp1.status_code == 200
        # 同名再注册
        code2 = db.create_invite_code("T001", max_uses=1, created_by="U001")
        resp2 = client.post("/api/auth/register", json={
            "invite_code": code2,
            "username": "dupuser",
            "password": "password456",
        })
        assert resp2.status_code == 409

    def test_register_short_password(self, client):
        """密码太短返回 422。"""
        resp = client.post("/api/auth/register", json={
            "invite_code": "inv_test",
            "username": "newuser",
            "password": "12345",
        })
        assert resp.status_code == 422

    def test_register_short_username(self, client):
        """用户名太短返回 422。"""
        resp = client.post("/api/auth/register", json={
            "invite_code": "inv_test",
            "username": "a",
            "password": "password123",
        })
        assert resp.status_code == 422


# ── Admin invite-code endpoint tests ──


class TestAdminInviteCodeEndpoints:

    @pytest.fixture
    def admin_client(self, db):
        """带 admin token 的测试客户端。"""
        from fastapi.testclient import TestClient
        from main import app

        with patch("dependencies.get_database", return_value=db):
            with patch("config.settings") as mock_settings:
                mock_settings.auth_enabled = True
                mock_settings.auth_jwt_secret = "test-secret-key-12345678"
                mock_settings.auth_jwt_algorithm = "HS256"
                mock_settings.auth_session_expire_s = 3600
                mock_settings.app_debug = False

                from core.auth import issue_session_token
                token = issue_session_token(
                    user_id="U001", tenant_id="T001", roles=["admin"],
                    secret="test-secret-key-12345678", algorithm="HS256", expires_in=3600,
                )
                client = TestClient(app)
                client.headers["Authorization"] = f"Bearer {token}"
                yield client

    def test_create_invite_code(self, admin_client):
        """管理员创建邀请码。"""
        resp = admin_client.post("/api/admin/tenants/T001/invite-codes", json={
            "roles": ["user"],
            "max_uses": 5,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"].startswith("inv_")
        assert data["max_uses"] == 5

    def test_list_invite_codes(self, db, admin_client):
        """管理员列出邀请码。"""
        db.create_invite_code("T001", created_by="U001")
        resp = admin_client.get("/api/admin/tenants/T001/invite-codes")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_revoke_invite_code(self, db, admin_client):
        """管理员撤销邀请码。"""
        code = db.create_invite_code("T001", created_by="U001")
        resp = admin_client.post(f"/api/admin/tenants/T001/invite-codes/{code}/revoke")
        assert resp.status_code == 200

    def test_revoke_not_found(self, admin_client):
        """撤销不存在的邀请码返回 404。"""
        resp = admin_client.post("/api/admin/tenants/T001/invite-codes/inv_nonexistent/revoke")
        assert resp.status_code == 404
