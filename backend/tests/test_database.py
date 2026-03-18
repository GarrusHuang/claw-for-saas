"""Tests for services/database.py — DatabaseService, password/key hashing."""
import sys
import os
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.database import (
    DatabaseService,
    hash_password,
    verify_password,
    hash_api_key,
    TenantRecord,
    UserRecord,
    ApiKeyRecord,
)


# ── Password Hashing ──


class TestPasswordHashing:
    def test_hash_and_verify(self):
        pw = "my_secret_password"
        hashed = hash_password(pw)
        assert verify_password(pw, hashed) is True

    def test_wrong_password(self):
        hashed = hash_password("correct")
        assert verify_password("wrong", hashed) is False

    def test_hash_format(self):
        """bcrypt hash starts with $2b$ prefix."""
        hashed = hash_password("test")
        assert hashed.startswith("$2b$"), f"Expected bcrypt format, got: {hashed[:20]}"
        # bcrypt hash is 60 characters total
        assert len(hashed) == 60

    def test_different_hashes_for_same_password(self):
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2  # Different salt each time

    def test_invalid_hash_format(self):
        assert verify_password("test", "no_colon") is False


class TestApiKeyHashing:
    def test_hash_deterministic(self):
        key = "clk_test123"
        assert hash_api_key(key) == hash_api_key(key)

    def test_different_keys_different_hashes(self):
        assert hash_api_key("key_a") != hash_api_key("key_b")


# ── DatabaseService: Tenant CRUD ──


class TestTenantCRUD:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.db = DatabaseService(db_path=str(tmp_path / "test.db"))

    def test_create_tenant(self):
        t = self.db.create_tenant("T001", "Acme Corp")
        assert t.tenant_id == "T001"
        assert t.name == "Acme Corp"
        assert t.status == "active"
        assert t.max_users == 100

    def test_create_duplicate_tenant(self):
        self.db.create_tenant("T001", "Acme")
        with pytest.raises(ValueError, match="already exists"):
            self.db.create_tenant("T001", "Dupe")

    def test_get_tenant(self):
        self.db.create_tenant("T001", "Acme")
        t = self.db.get_tenant("T001")
        assert t is not None
        assert t.name == "Acme"

    def test_get_tenant_not_found(self):
        assert self.db.get_tenant("nope") is None

    def test_list_tenants(self):
        self.db.create_tenant("T001", "A")
        self.db.create_tenant("T002", "B")
        tenants = self.db.list_tenants()
        assert len(tenants) == 2

    def test_update_tenant(self):
        self.db.create_tenant("T001", "Old")
        assert self.db.update_tenant("T001", name="New") is True
        t = self.db.get_tenant("T001")
        assert t.name == "New"

    def test_update_tenant_status(self):
        self.db.create_tenant("T001", "Acme")
        self.db.update_tenant("T001", status="disabled")
        t = self.db.get_tenant("T001")
        assert t.status == "disabled"

    def test_update_nonexistent(self):
        assert self.db.update_tenant("nope", name="X") is False

    def test_update_no_fields(self):
        self.db.create_tenant("T001", "Acme")
        assert self.db.update_tenant("T001") is False

    def test_delete_tenant(self):
        self.db.create_tenant("T001", "Acme")
        assert self.db.delete_tenant("T001") is True
        assert self.db.get_tenant("T001") is None

    def test_delete_nonexistent(self):
        assert self.db.delete_tenant("nope") is False

    def test_delete_cascades_users_and_keys(self):
        self.db.create_tenant("T001", "Acme")
        self.db.create_user("T001", "U1", "user1", "pw")
        self.db.create_api_key("T001", "test key")
        self.db.delete_tenant("T001")
        assert self.db.list_users("T001") == []
        assert self.db.list_api_keys("T001") == []


# ── DatabaseService: User CRUD ──


class TestUserCRUD:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.db = DatabaseService(db_path=str(tmp_path / "test.db"))
        self.db.create_tenant("T001", "Acme")

    def test_create_user(self):
        u = self.db.create_user("T001", "U1", "alice", "pw123", roles=["admin"])
        assert u.user_id == "U1"
        assert u.username == "alice"
        assert u.roles == ["admin"]

    def test_create_duplicate_user_id(self):
        self.db.create_user("T001", "U1", "alice", "pw")
        with pytest.raises(ValueError, match="already exists"):
            self.db.create_user("T001", "U1", "bob", "pw")

    def test_create_duplicate_username(self):
        self.db.create_user("T001", "U1", "alice", "pw")
        with pytest.raises(ValueError, match="Username already exists"):
            self.db.create_user("T001", "U2", "alice", "pw")

    def test_get_user(self):
        self.db.create_user("T001", "U1", "alice", "pw")
        u = self.db.get_user("T001", "U1")
        assert u is not None
        assert u.username == "alice"

    def test_get_user_not_found(self):
        assert self.db.get_user("T001", "nope") is None

    def test_get_user_by_username(self):
        self.db.create_user("T001", "U1", "alice", "pw")
        u = self.db.get_user_by_username("T001", "alice")
        assert u is not None
        assert u.user_id == "U1"

    def test_list_users(self):
        self.db.create_user("T001", "U1", "a", "pw")
        self.db.create_user("T001", "U2", "b", "pw")
        users = self.db.list_users("T001")
        assert len(users) == 2

    def test_update_user_password(self):
        self.db.create_user("T001", "U1", "alice", "old_pw")
        self.db.update_user("T001", "U1", password="new_pw")
        u = self.db.authenticate_user("T001", "alice", "new_pw")
        assert u is not None

    def test_update_user_roles(self):
        self.db.create_user("T001", "U1", "alice", "pw")
        self.db.update_user("T001", "U1", roles=["admin", "editor"])
        u = self.db.get_user("T001", "U1")
        assert u.roles == ["admin", "editor"]

    def test_update_user_status(self):
        self.db.create_user("T001", "U1", "alice", "pw")
        self.db.update_user("T001", "U1", status="disabled")
        u = self.db.get_user("T001", "U1")
        assert u.status == "disabled"

    def test_delete_user(self):
        self.db.create_user("T001", "U1", "alice", "pw")
        assert self.db.delete_user("T001", "U1") is True
        assert self.db.get_user("T001", "U1") is None

    def test_delete_nonexistent_user(self):
        assert self.db.delete_user("T001", "nope") is False

    def test_authenticate_success(self):
        self.db.create_user("T001", "U1", "alice", "pw123")
        u = self.db.authenticate_user("T001", "alice", "pw123")
        assert u is not None
        assert u.user_id == "U1"

    def test_authenticate_wrong_password(self):
        self.db.create_user("T001", "U1", "alice", "pw123")
        assert self.db.authenticate_user("T001", "alice", "wrong") is None

    def test_authenticate_nonexistent_user(self):
        assert self.db.authenticate_user("T001", "nobody", "pw") is None

    def test_authenticate_disabled_user(self):
        self.db.create_user("T001", "U1", "alice", "pw123")
        self.db.update_user("T001", "U1", status="disabled")
        assert self.db.authenticate_user("T001", "alice", "pw123") is None


# ── DatabaseService: API Key CRUD ──


class TestApiKeyCRUD:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.db = DatabaseService(db_path=str(tmp_path / "test.db"))
        self.db.create_tenant("T001", "Acme")

    def test_create_api_key(self):
        raw_key, record = self.db.create_api_key("T001", "integration key")
        assert raw_key.startswith("clk_")
        assert record.tenant_id == "T001"
        assert record.description == "integration key"
        assert record.status == "active"

    def test_verify_api_key(self):
        raw_key, _ = self.db.create_api_key("T001", "test")
        record = self.db.verify_api_key(raw_key)
        assert record is not None
        assert record.tenant_id == "T001"

    def test_verify_invalid_key(self):
        assert self.db.verify_api_key("clk_invalid_key") is None

    def test_verify_revoked_key(self):
        raw_key, record = self.db.create_api_key("T001", "test")
        self.db.revoke_api_key(record.key_id)
        assert self.db.verify_api_key(raw_key) is None

    def test_verify_expired_key(self):
        # Create key that expires in -1 days (already expired)
        raw_key, record = self.db.create_api_key("T001", "test", expires_in_days=-1)
        assert self.db.verify_api_key(raw_key) is None

    def test_list_api_keys(self):
        self.db.create_api_key("T001", "key1")
        self.db.create_api_key("T001", "key2")
        keys = self.db.list_api_keys("T001")
        assert len(keys) == 2

    def test_revoke_api_key(self):
        _, record = self.db.create_api_key("T001", "test")
        assert self.db.revoke_api_key(record.key_id) is True
        keys = self.db.list_api_keys("T001")
        assert keys[0].status == "revoked"

    def test_delete_api_key(self):
        _, record = self.db.create_api_key("T001", "test")
        assert self.db.delete_api_key(record.key_id) is True
        assert self.db.list_api_keys("T001") == []


# ── Bootstrap ──


class TestBootstrap:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.db = DatabaseService(db_path=str(tmp_path / "test.db"))

    def test_ensure_default_tenant_and_admin(self):
        self.db.ensure_default_tenant_and_admin()
        t = self.db.get_tenant("default")
        assert t is not None
        u = self.db.get_user("default", "U001")
        assert u is not None
        assert u.username == "admin"
        assert "admin" in u.roles

    def test_idempotent(self):
        self.db.ensure_default_tenant_and_admin()
        self.db.ensure_default_tenant_and_admin()  # Should not raise
        assert len(self.db.list_users("default")) == 1

    def test_custom_ids(self):
        self.db.ensure_default_tenant_and_admin(
            tenant_id="custom",
            admin_user_id="A001",
            admin_username="superadmin",
            admin_password="secure123",
        )
        u = self.db.authenticate_user("custom", "superadmin", "secure123")
        assert u is not None
        assert u.user_id == "A001"
