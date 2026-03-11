"""
A6 数据锁定层 — DataLockRegistry。

统一 DataLock 机制，宿主通过配置或 MCP 声明锁定字段。
Agent 工具写入时自动校验。

锁定级别:
- readonly: 不可修改
- audit: 可修改但记录日志

锁定范围:
- field: 字段级 (key 指定字段名)
- global: 全局级 (所有写操作需校验)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class LockLevel(str, Enum):
    """锁定级别。"""
    READONLY = "readonly"  # 不可修改
    AUDIT = "audit"  # 可修改但记录日志


class LockScope(str, Enum):
    """锁定范围。"""
    FIELD = "field"  # 字段级
    GLOBAL = "global"  # 全局级


@dataclass
class DataLock:
    """单个数据锁定规则。"""
    key: str  # 字段名或全局标识
    level: LockLevel = LockLevel.READONLY
    scope: LockScope = LockScope.FIELD
    reason: str = ""  # 锁定原因
    source: str = ""  # 锁定来源 (host/config/mcp)


@dataclass
class LockViolation:
    """锁定违规记录。"""
    key: str
    level: LockLevel
    attempted_value: str
    reason: str
    timestamp: float = 0.0

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.time()


class DataLockRegistry:
    """
    数据锁定注册表。

    宿主系统或配置声明锁定字段，Agent 工具写入时校验。
    """

    def __init__(self) -> None:
        self._locks: dict[str, DataLock] = {}
        self._audit_log: list[LockViolation] = []

    def register(self, lock: DataLock) -> None:
        """注册一个锁定规则。"""
        self._locks[lock.key] = lock
        logger.debug(f"DataLock registered: {lock.key} ({lock.level.value})")

    def register_many(self, locks: list[DataLock]) -> None:
        """批量注册锁定规则。"""
        for lock in locks:
            self.register(lock)

    def unregister(self, key: str) -> bool:
        """注销一个锁定规则。"""
        if key in self._locks:
            del self._locks[key]
            return True
        return False

    def clear(self) -> None:
        """清除所有锁定规则。"""
        self._locks.clear()

    def check(self, key: str, value: str = "") -> LockViolation | None:
        """
        校验是否允许修改指定字段。

        Returns:
            None 如果允许修改, LockViolation 如果被锁定。
            audit 级别返回 violation (记录日志) 但不阻止。
        """
        lock = self._locks.get(key)
        if not lock:
            # 检查全局锁
            for lk in self._locks.values():
                if lk.scope == LockScope.GLOBAL:
                    lock = lk
                    break

        if not lock:
            return None

        violation = LockViolation(
            key=key,
            level=lock.level,
            attempted_value=value[:200] if value else "",
            reason=lock.reason or f"字段 {key} 被锁定 ({lock.level.value})",
        )

        if lock.level == LockLevel.AUDIT:
            # 审计级别: 记录但不阻止
            self._audit_log.append(violation)
            logger.info(f"DataLock audit: {key} modified (reason: {lock.reason})")
            return None  # 不阻止

        # readonly: 阻止
        self._audit_log.append(violation)
        logger.warning(f"DataLock blocked: {key} (reason: {lock.reason})")
        return violation

    def is_locked(self, key: str) -> bool:
        """检查字段是否被锁定（任何级别）。"""
        return key in self._locks or any(
            lk.scope == LockScope.GLOBAL for lk in self._locks.values()
        )

    def get_lock(self, key: str) -> DataLock | None:
        """获取字段的锁定规则。"""
        return self._locks.get(key)

    def list_locks(self) -> list[dict]:
        """列出所有锁定规则。"""
        return [
            {
                "key": lock.key,
                "level": lock.level.value,
                "scope": lock.scope.value,
                "reason": lock.reason,
                "source": lock.source,
            }
            for lock in self._locks.values()
        ]

    def get_audit_log(self, limit: int = 100) -> list[dict]:
        """获取审计日志。"""
        entries = self._audit_log[-limit:]
        return [
            {
                "key": v.key,
                "level": v.level.value,
                "attempted_value": v.attempted_value,
                "reason": v.reason,
                "timestamp": v.timestamp,
            }
            for v in entries
        ]

    def clear_audit_log(self) -> None:
        """清除审计日志。"""
        self._audit_log.clear()
