"""
T5: 并发会话访问测试。

验证同一 session 的并发请求被正确处理 (一个获得锁，另一个被拒绝)。
"""
from __future__ import annotations

import os
import fcntl
import tempfile
import pytest

from agent.gateway import AgentGateway, SessionBusyError
from agent.session import SessionManager


class TestSessionLocking:
    """Session 级文件锁并发控制。"""

    def test_acquire_lock_success(self, tmp_path):
        """首次获取锁应成功。"""
        sm = SessionManager(base_dir=str(tmp_path / "sessions"))
        session_id = sm.create_session("T1", "U1")

        gw = AgentGateway.__new__(AgentGateway)
        gw.session_manager = sm

        fd = gw._acquire_session_lock("T1", "U1", session_id)
        assert fd > 0

        # 清理
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

    def test_concurrent_lock_raises(self, tmp_path):
        """同一 session 的第二个锁应抛出 SessionBusyError。"""
        sm = SessionManager(base_dir=str(tmp_path / "sessions"))
        session_id = sm.create_session("T1", "U1")

        gw = AgentGateway.__new__(AgentGateway)
        gw.session_manager = sm

        # 第一个锁
        fd1 = gw._acquire_session_lock("T1", "U1", session_id)

        # 第二个锁应失败
        with pytest.raises(SessionBusyError) as exc_info:
            gw._acquire_session_lock("T1", "U1", session_id)

        assert session_id in str(exc_info.value)

        # 清理
        fcntl.flock(fd1, fcntl.LOCK_UN)
        os.close(fd1)

    def test_release_then_reacquire(self, tmp_path):
        """释放锁后应能重新获取。"""
        sm = SessionManager(base_dir=str(tmp_path / "sessions"))
        session_id = sm.create_session("T1", "U1")

        gw = AgentGateway.__new__(AgentGateway)
        gw.session_manager = sm

        # 获取并释放
        fd1 = gw._acquire_session_lock("T1", "U1", session_id)
        fcntl.flock(fd1, fcntl.LOCK_UN)
        os.close(fd1)

        # 应能重新获取
        fd2 = gw._acquire_session_lock("T1", "U1", session_id)
        assert fd2 > 0

        fcntl.flock(fd2, fcntl.LOCK_UN)
        os.close(fd2)

    def test_different_sessions_no_conflict(self, tmp_path):
        """不同 session 的锁不冲突。"""
        sm = SessionManager(base_dir=str(tmp_path / "sessions"))
        s1 = sm.create_session("T1", "U1")
        s2 = sm.create_session("T1", "U1")

        gw = AgentGateway.__new__(AgentGateway)
        gw.session_manager = sm

        fd1 = gw._acquire_session_lock("T1", "U1", s1)
        fd2 = gw._acquire_session_lock("T1", "U1", s2)

        assert fd1 > 0
        assert fd2 > 0

        fcntl.flock(fd1, fcntl.LOCK_UN)
        os.close(fd1)
        fcntl.flock(fd2, fcntl.LOCK_UN)
        os.close(fd2)


class TestOrphanLockCleanup:
    """孤儿 lock 文件清理。"""

    def test_cleanup_old_locks(self, tmp_path):
        """超过 max_age 的 lock 文件应被清理。"""
        sm = SessionManager(base_dir=str(tmp_path / "sessions"))
        sm.create_session("T1", "U1")

        # 创建一个 lock 文件并设置旧 mtime
        lock_dir = tmp_path / "sessions" / "T1" / "U1"
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_file = lock_dir / "old-session.lock"
        lock_file.touch()
        # 设置 2 小时前的 mtime
        import time
        old_time = time.time() - 7200
        os.utime(lock_file, (old_time, old_time))

        cleaned = sm.cleanup_orphan_locks(max_age_s=3600)
        assert cleaned >= 1
        assert not lock_file.exists()

    def test_keep_recent_locks(self, tmp_path):
        """新的 lock 文件不应被清理。"""
        sm = SessionManager(base_dir=str(tmp_path / "sessions"))
        lock_dir = tmp_path / "sessions" / "T1" / "U1"
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_file = lock_dir / "recent.lock"
        lock_file.touch()

        cleaned = sm.cleanup_orphan_locks(max_age_s=3600)
        assert cleaned == 0
        assert lock_file.exists()
