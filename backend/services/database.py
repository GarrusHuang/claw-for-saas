"""
SQLite 数据库服务 — 租户、用户、API Key 管理。

表结构:
  - tenants: 租户信息
  - users: 用户信息 (属于某个租户)
  - api_keys: API Key (属于某个租户)

Usage:
    db = DatabaseService("data/claw.db")
    db.create_tenant("T001", "Acme Corp")
    db.create_user("T001", "U001", "admin", hashed_pw, roles=["admin"])
    db.create_api_key("T001", "my-key", "for integration")
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class TenantRecord:
    """租户记录。"""
    tenant_id: str
    name: str
    status: str = "active"  # active | disabled
    max_users: int = 100
    created_at: float = 0.0


@dataclass
class UserRecord:
    """用户记录。"""
    user_id: str
    tenant_id: str
    username: str
    password_hash: str
    roles: list[str] = field(default_factory=list)
    status: str = "active"  # active | disabled
    created_at: float = 0.0


@dataclass
class ApiKeyRecord:
    """API Key 记录。"""
    key_id: str
    tenant_id: str
    key_hash: str
    description: str = ""
    status: str = "active"  # active | revoked
    created_at: float = 0.0
    expires_at: float | None = None


def hash_password(password: str) -> str:
    """Hash password with SHA-256 + salt."""
    salt = secrets.token_hex(16)
    hashed = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
    return f"{salt}:{hashed}"


def verify_password(password: str, password_hash: str) -> bool:
    """Verify password against stored hash."""
    parts = password_hash.split(":", 1)
    if len(parts) != 2:
        return False
    salt, stored_hash = parts
    computed = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
    return secrets.compare_digest(computed, stored_hash)


def hash_api_key(key: str) -> str:
    """Hash API key with SHA-256."""
    return hashlib.sha256(key.encode()).hexdigest()


class DatabaseService:
    """SQLite 数据库服务。"""

    def __init__(self, db_path: str = "data/claw.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        """初始化表结构。"""
        conn = self._get_conn()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS tenants (
                    tenant_id   TEXT PRIMARY KEY,
                    name        TEXT NOT NULL,
                    status      TEXT NOT NULL DEFAULT 'active',
                    max_users   INTEGER NOT NULL DEFAULT 100,
                    created_at  REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS users (
                    user_id       TEXT NOT NULL,
                    tenant_id     TEXT NOT NULL,
                    username      TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    roles         TEXT NOT NULL DEFAULT '[]',
                    status        TEXT NOT NULL DEFAULT 'active',
                    created_at    REAL NOT NULL,
                    PRIMARY KEY (tenant_id, user_id),
                    FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id),
                    UNIQUE (tenant_id, username)
                );

                CREATE TABLE IF NOT EXISTS api_keys (
                    key_id      TEXT PRIMARY KEY,
                    tenant_id   TEXT NOT NULL,
                    key_hash    TEXT NOT NULL UNIQUE,
                    description TEXT NOT NULL DEFAULT '',
                    status      TEXT NOT NULL DEFAULT 'active',
                    created_at  REAL NOT NULL,
                    expires_at  REAL,
                    FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)
                );

                -- A10: 用量统计 — 原始 pipeline 执行记录
                CREATE TABLE IF NOT EXISTS usage_events (
                    id                INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id         TEXT NOT NULL,
                    user_id           TEXT NOT NULL,
                    session_id        TEXT NOT NULL,
                    business_type     TEXT NOT NULL DEFAULT 'general_chat',
                    prompt_tokens     INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens      INTEGER NOT NULL DEFAULT 0,
                    tool_call_count   INTEGER NOT NULL DEFAULT 0,
                    iterations        INTEGER NOT NULL DEFAULT 0,
                    duration_ms       REAL NOT NULL DEFAULT 0.0,
                    status            TEXT NOT NULL DEFAULT 'success',
                    model             TEXT NOT NULL DEFAULT '',
                    tool_names        TEXT NOT NULL DEFAULT '[]',
                    created_at        REAL NOT NULL,
                    FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)
                );
                CREATE INDEX IF NOT EXISTS idx_usage_tenant_date
                    ON usage_events(tenant_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_usage_user_date
                    ON usage_events(tenant_id, user_id, created_at);

                -- A10: 用量统计 — 日汇总（UPSERT 更新）
                CREATE TABLE IF NOT EXISTS usage_daily (
                    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id               TEXT NOT NULL,
                    user_id                 TEXT NOT NULL,
                    date                    TEXT NOT NULL,
                    total_requests          INTEGER NOT NULL DEFAULT 0,
                    total_prompt_tokens     INTEGER NOT NULL DEFAULT 0,
                    total_completion_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens            INTEGER NOT NULL DEFAULT 0,
                    total_tool_calls        INTEGER NOT NULL DEFAULT 0,
                    total_duration_ms       REAL NOT NULL DEFAULT 0.0,
                    success_count           INTEGER NOT NULL DEFAULT 0,
                    failed_count            INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(tenant_id, user_id, date)
                );
                CREATE INDEX IF NOT EXISTS idx_daily_tenant_date
                    ON usage_daily(tenant_id, date);
            """)
            conn.commit()
            logger.info(f"Database initialized: {self.db_path}")
        finally:
            conn.close()

    # ── Tenant CRUD ──

    def create_tenant(
        self, tenant_id: str, name: str, max_users: int = 100
    ) -> TenantRecord:
        """创建租户。"""
        now = time.time()
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO tenants (tenant_id, name, max_users, created_at) VALUES (?, ?, ?, ?)",
                (tenant_id, name, max_users, now),
            )
            conn.commit()
            return TenantRecord(
                tenant_id=tenant_id, name=name, max_users=max_users, created_at=now
            )
        except sqlite3.IntegrityError:
            raise ValueError(f"Tenant already exists: {tenant_id}")
        finally:
            conn.close()

    def get_tenant(self, tenant_id: str) -> TenantRecord | None:
        """获取租户。"""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM tenants WHERE tenant_id = ?", (tenant_id,)
            ).fetchone()
            if not row:
                return None
            return TenantRecord(**dict(row))
        finally:
            conn.close()

    def list_tenants(self) -> list[TenantRecord]:
        """列出所有租户。"""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM tenants ORDER BY created_at"
            ).fetchall()
            return [TenantRecord(**dict(r)) for r in rows]
        finally:
            conn.close()

    def update_tenant(
        self, tenant_id: str, name: str | None = None, status: str | None = None, max_users: int | None = None
    ) -> bool:
        """更新租户信息。"""
        updates = []
        params = []
        if name is not None:
            updates.append("name = ?")
            params.append(name)
        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if max_users is not None:
            updates.append("max_users = ?")
            params.append(max_users)
        if not updates:
            return False
        params.append(tenant_id)
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                f"UPDATE tenants SET {', '.join(updates)} WHERE tenant_id = ?", params
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def delete_tenant(self, tenant_id: str) -> bool:
        """删除租户（级联删除用户和 API Key）。"""
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM api_keys WHERE tenant_id = ?", (tenant_id,))
            conn.execute("DELETE FROM users WHERE tenant_id = ?", (tenant_id,))
            cursor = conn.execute("DELETE FROM tenants WHERE tenant_id = ?", (tenant_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    # ── User CRUD ──

    def create_user(
        self,
        tenant_id: str,
        user_id: str,
        username: str,
        password: str,
        roles: list[str] | None = None,
    ) -> UserRecord:
        """创建用户。"""
        import json

        now = time.time()
        pw_hash = hash_password(password)
        roles = roles or []
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO users (user_id, tenant_id, username, password_hash, roles, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, tenant_id, username, pw_hash, json.dumps(roles), now),
            )
            conn.commit()
            return UserRecord(
                user_id=user_id,
                tenant_id=tenant_id,
                username=username,
                password_hash=pw_hash,
                roles=roles,
                created_at=now,
            )
        except sqlite3.IntegrityError as e:
            if "UNIQUE" in str(e) and "username" in str(e):
                raise ValueError(f"Username already exists in tenant {tenant_id}: {username}")
            raise ValueError(f"User already exists: {tenant_id}/{user_id}")
        finally:
            conn.close()

    def get_user(self, tenant_id: str, user_id: str) -> UserRecord | None:
        """获取用户。"""
        import json

        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM users WHERE tenant_id = ? AND user_id = ?",
                (tenant_id, user_id),
            ).fetchone()
            if not row:
                return None
            d = dict(row)
            d["roles"] = json.loads(d["roles"])
            return UserRecord(**d)
        finally:
            conn.close()

    def get_user_by_username(self, tenant_id: str, username: str) -> UserRecord | None:
        """按用户名查找用户。"""
        import json

        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM users WHERE tenant_id = ? AND username = ?",
                (tenant_id, username),
            ).fetchone()
            if not row:
                return None
            d = dict(row)
            d["roles"] = json.loads(d["roles"])
            return UserRecord(**d)
        finally:
            conn.close()

    def list_users(self, tenant_id: str) -> list[UserRecord]:
        """列出租户下所有用户。"""
        import json

        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM users WHERE tenant_id = ? ORDER BY created_at",
                (tenant_id,),
            ).fetchall()
            results = []
            for r in rows:
                d = dict(r)
                d["roles"] = json.loads(d["roles"])
                results.append(UserRecord(**d))
            return results
        finally:
            conn.close()

    def update_user(
        self,
        tenant_id: str,
        user_id: str,
        password: str | None = None,
        roles: list[str] | None = None,
        status: str | None = None,
    ) -> bool:
        """更新用户。"""
        import json

        updates = []
        params = []
        if password is not None:
            updates.append("password_hash = ?")
            params.append(hash_password(password))
        if roles is not None:
            updates.append("roles = ?")
            params.append(json.dumps(roles))
        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if not updates:
            return False
        params.extend([tenant_id, user_id])
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                f"UPDATE users SET {', '.join(updates)} WHERE tenant_id = ? AND user_id = ?",
                params,
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def delete_user(self, tenant_id: str, user_id: str) -> bool:
        """删除用户。"""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "DELETE FROM users WHERE tenant_id = ? AND user_id = ?",
                (tenant_id, user_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def authenticate_user(self, tenant_id: str, username: str, password: str) -> UserRecord | None:
        """验证用户名密码，返回用户记录或 None。"""
        user = self.get_user_by_username(tenant_id, username)
        if not user:
            return None
        if user.status != "active":
            return None
        if not verify_password(password, user.password_hash):
            return None
        return user

    # ── API Key CRUD ──

    def create_api_key(
        self,
        tenant_id: str,
        description: str = "",
        expires_in_days: int | None = None,
    ) -> tuple[str, ApiKeyRecord]:
        """
        创建 API Key。

        Returns:
            (raw_key, ApiKeyRecord) — raw_key 仅此时可见，之后只存 hash
        """
        now = time.time()
        key_id = secrets.token_hex(8)
        raw_key = f"clk_{secrets.token_urlsafe(32)}"
        k_hash = hash_api_key(raw_key)
        expires_at = (now + expires_in_days * 86400) if expires_in_days else None

        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO api_keys (key_id, tenant_id, key_hash, description, created_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (key_id, tenant_id, k_hash, description, now, expires_at),
            )
            conn.commit()
            record = ApiKeyRecord(
                key_id=key_id,
                tenant_id=tenant_id,
                key_hash=k_hash,
                description=description,
                created_at=now,
                expires_at=expires_at,
            )
            return raw_key, record
        finally:
            conn.close()

    def verify_api_key(self, raw_key: str) -> ApiKeyRecord | None:
        """验证 API Key，返回记录或 None。"""
        k_hash = hash_api_key(raw_key)
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM api_keys WHERE key_hash = ? AND status = 'active'",
                (k_hash,),
            ).fetchone()
            if not row:
                return None
            record = ApiKeyRecord(**dict(row))
            # 检查过期
            if record.expires_at and time.time() > record.expires_at:
                return None
            return record
        finally:
            conn.close()

    def list_api_keys(self, tenant_id: str) -> list[ApiKeyRecord]:
        """列出租户的所有 API Key。"""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM api_keys WHERE tenant_id = ? ORDER BY created_at",
                (tenant_id,),
            ).fetchall()
            return [ApiKeyRecord(**dict(r)) for r in rows]
        finally:
            conn.close()

    def revoke_api_key(self, key_id: str) -> bool:
        """撤销 API Key。"""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "UPDATE api_keys SET status = 'revoked' WHERE key_id = ?",
                (key_id,),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def delete_api_key(self, key_id: str) -> bool:
        """删除 API Key。"""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "DELETE FROM api_keys WHERE key_id = ?", (key_id,)
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    # ── Bootstrap ──

    def ensure_default_tenant_and_admin(
        self,
        tenant_id: str = "default",
        admin_user_id: str = "U001",
        admin_username: str = "admin",
        admin_password: str = "admin123",
    ) -> None:
        """确保默认租户和管理员存在（首次启动自动创建）。"""
        if not self.get_tenant(tenant_id):
            self.create_tenant(tenant_id, "Default Tenant")
            logger.info(f"Created default tenant: {tenant_id}")

        if not self.get_user(tenant_id, admin_user_id):
            self.create_user(
                tenant_id=tenant_id,
                user_id=admin_user_id,
                username=admin_username,
                password=admin_password,
                roles=["admin"],
            )
            logger.info(
                f"Created default admin: {admin_username} (tenant={tenant_id}, "
                f"user_id={admin_user_id}) — CHANGE PASSWORD IN PRODUCTION!"
            )
