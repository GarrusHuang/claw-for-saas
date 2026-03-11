"""
Tests for core/data_lock.py — DataLockRegistry.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from core.data_lock import (
    DataLockRegistry, DataLock, LockLevel, LockScope, LockViolation,
)


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

@pytest.fixture
def registry():
    return DataLockRegistry()


@pytest.fixture
def registry_with_locks():
    reg = DataLockRegistry()
    reg.register(DataLock(
        key="salary",
        level=LockLevel.READONLY,
        scope=LockScope.FIELD,
        reason="薪资字段不可修改",
        source="config",
    ))
    reg.register(DataLock(
        key="department",
        level=LockLevel.AUDIT,
        scope=LockScope.FIELD,
        reason="部门变更需审计",
        source="config",
    ))
    return reg


# ──────────────────────────────────────────────
# Registration
# ──────────────────────────────────────────────

class TestRegistration:
    """Tests for lock registration and management."""

    def test_register_lock(self, registry):
        lock = DataLock(key="field1", level=LockLevel.READONLY)
        registry.register(lock)
        assert registry.is_locked("field1")

    def test_register_many(self, registry):
        locks = [
            DataLock(key="f1", level=LockLevel.READONLY),
            DataLock(key="f2", level=LockLevel.AUDIT),
        ]
        registry.register_many(locks)
        assert registry.is_locked("f1")
        assert registry.is_locked("f2")

    def test_unregister(self, registry):
        registry.register(DataLock(key="f1", level=LockLevel.READONLY))
        assert registry.unregister("f1") is True
        assert not registry.is_locked("f1")

    def test_unregister_nonexistent(self, registry):
        assert registry.unregister("nonexistent") is False

    def test_clear(self, registry_with_locks):
        registry_with_locks.clear()
        assert len(registry_with_locks.list_locks()) == 0

    def test_get_lock(self, registry_with_locks):
        lock = registry_with_locks.get_lock("salary")
        assert lock is not None
        assert lock.level == LockLevel.READONLY

    def test_get_lock_nonexistent(self, registry):
        assert registry.get_lock("nonexistent") is None

    def test_list_locks(self, registry_with_locks):
        locks = registry_with_locks.list_locks()
        assert len(locks) == 2
        names = {l["key"] for l in locks}
        assert names == {"salary", "department"}


# ──────────────────────────────────────────────
# Check (readonly vs audit)
# ──────────────────────────────────────────────

class TestCheck:
    """Tests for lock checking (readonly blocks, audit allows)."""

    def test_readonly_blocks(self, registry_with_locks):
        violation = registry_with_locks.check("salary", "100000")
        assert violation is not None
        assert violation.level == LockLevel.READONLY
        assert violation.key == "salary"

    def test_audit_allows(self, registry_with_locks):
        result = registry_with_locks.check("department", "Engineering")
        assert result is None  # audit doesn't block

    def test_unlocked_field_allows(self, registry_with_locks):
        result = registry_with_locks.check("email", "test@example.com")
        assert result is None

    def test_readonly_truncates_attempted_value(self, registry_with_locks):
        long_value = "x" * 500
        violation = registry_with_locks.check("salary", long_value)
        assert violation is not None
        assert len(violation.attempted_value) <= 200

    def test_violation_has_timestamp(self, registry_with_locks):
        violation = registry_with_locks.check("salary", "val")
        assert violation.timestamp > 0


# ──────────────────────────────────────────────
# Global lock
# ──────────────────────────────────────────────

class TestGlobalLock:
    """Tests for global-scope locks."""

    def test_global_lock_blocks_any_field(self, registry):
        registry.register(DataLock(
            key="*",
            level=LockLevel.READONLY,
            scope=LockScope.GLOBAL,
            reason="System in maintenance mode",
        ))
        violation = registry.check("any_field", "value")
        assert violation is not None
        assert "any_field" in violation.key

    def test_field_lock_takes_precedence_over_global(self, registry):
        registry.register(DataLock(
            key="*",
            level=LockLevel.AUDIT,
            scope=LockScope.GLOBAL,
            reason="Global audit",
        ))
        registry.register(DataLock(
            key="salary",
            level=LockLevel.READONLY,
            scope=LockScope.FIELD,
            reason="Salary locked",
        ))
        # salary has field-level readonly -> blocked
        violation = registry.check("salary", "100")
        assert violation is not None
        assert violation.level == LockLevel.READONLY


# ──────────────────────────────────────────────
# Audit log
# ──────────────────────────────────────────────

class TestAuditLog:
    """Tests for audit logging."""

    def test_readonly_logged(self, registry_with_locks):
        registry_with_locks.check("salary", "100")
        log = registry_with_locks.get_audit_log()
        assert len(log) >= 1
        assert log[-1]["key"] == "salary"

    def test_audit_logged(self, registry_with_locks):
        registry_with_locks.check("department", "Engineering")
        log = registry_with_locks.get_audit_log()
        assert len(log) >= 1
        assert log[-1]["key"] == "department"

    def test_clear_audit_log(self, registry_with_locks):
        registry_with_locks.check("salary", "100")
        registry_with_locks.clear_audit_log()
        assert len(registry_with_locks.get_audit_log()) == 0

    def test_audit_log_limit(self, registry):
        registry.register(DataLock(key="f1", level=LockLevel.READONLY))
        for i in range(150):
            registry.check("f1", str(i))
        log = registry.get_audit_log(limit=10)
        assert len(log) == 10


# ──────────────────────────────────────────────
# LockViolation dataclass
# ──────────────────────────────────────────────

class TestLockViolation:
    """Tests for LockViolation dataclass."""

    def test_auto_timestamp(self):
        v = LockViolation(key="k", level=LockLevel.READONLY, attempted_value="v", reason="r")
        assert v.timestamp > 0

    def test_explicit_timestamp(self):
        v = LockViolation(key="k", level=LockLevel.READONLY, attempted_value="v", reason="r", timestamp=123.0)
        assert v.timestamp == 123.0
