"""
SQLite 并发优化测试 — 4.2

验证:
- PRAGMA busy_timeout = 5000
- PRAGMA synchronous = NORMAL (值 1)
- PRAGMA cache_size = -8000
- 同线程两次 _get_conn() 返回同一连接
- 不同线程返回不同连接
- UsageService 同样的 PRAGMA 验证
"""
import threading

import pytest

from services.database import DatabaseService
from services.usage_service import UsageService


@pytest.fixture
def db_service(tmp_path):
    return DatabaseService(str(tmp_path / "test.db"))


@pytest.fixture
def usage_service(tmp_path):
    # 复用 db_service 创建的 db (需要表结构)
    db_path = str(tmp_path / "test_usage.db")
    db = DatabaseService(db_path)
    db.ensure_default_tenant_and_admin()
    return UsageService(db_path)


class TestDatabaseServicePragma:
    """DatabaseService PRAGMA 调优验证。"""

    def test_busy_timeout(self, db_service):
        conn = db_service._get_conn()
        val = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        assert val == 5000

    def test_synchronous_normal(self, db_service):
        conn = db_service._get_conn()
        val = conn.execute("PRAGMA synchronous").fetchone()[0]
        # NORMAL = 1
        assert val == 1

    def test_cache_size(self, db_service):
        conn = db_service._get_conn()
        val = conn.execute("PRAGMA cache_size").fetchone()[0]
        assert val == -8000

    def test_temp_store_memory(self, db_service):
        conn = db_service._get_conn()
        val = conn.execute("PRAGMA temp_store").fetchone()[0]
        # MEMORY = 2
        assert val == 2

    def test_journal_mode_wal(self, db_service):
        conn = db_service._get_conn()
        val = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert val.lower() == "wal"


class TestDatabaseServiceConnectionReuse:
    """线程本地连接复用验证。"""

    def test_same_thread_same_connection(self, db_service):
        """同线程两次 _get_conn() 返回同一连接对象。"""
        conn1 = db_service._get_conn()
        conn2 = db_service._get_conn()
        assert conn1 is conn2

    def test_different_thread_different_connection(self, db_service):
        """不同线程返回不同连接对象。"""
        main_conn = db_service._get_conn()
        thread_conn = [None]

        def worker():
            thread_conn[0] = db_service._get_conn()

        t = threading.Thread(target=worker)
        t.start()
        t.join()

        assert thread_conn[0] is not None
        assert thread_conn[0] is not main_conn

    def test_close_all_clears_connection(self, db_service):
        """close_all 后重新获取是新连接。"""
        conn1 = db_service._get_conn()
        db_service.close_all()
        conn2 = db_service._get_conn()
        assert conn1 is not conn2

    def test_connection_recovers_after_close(self, db_service):
        """连接被外部关闭后自动重建。"""
        conn1 = db_service._get_conn()
        conn1.close()
        # _get_conn 应检测到连接失效并创建新连接
        conn2 = db_service._get_conn()
        # 新连接应该能正常工作
        conn2.execute("SELECT 1").fetchone()


class TestUsageServicePragma:
    """UsageService PRAGMA 调优验证。"""

    def test_busy_timeout(self, usage_service):
        conn = usage_service._get_conn()
        val = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        assert val == 5000

    def test_synchronous_normal(self, usage_service):
        conn = usage_service._get_conn()
        val = conn.execute("PRAGMA synchronous").fetchone()[0]
        assert val == 1

    def test_cache_size(self, usage_service):
        conn = usage_service._get_conn()
        val = conn.execute("PRAGMA cache_size").fetchone()[0]
        assert val == -8000

    def test_same_thread_reuse(self, usage_service):
        conn1 = usage_service._get_conn()
        conn2 = usage_service._get_conn()
        assert conn1 is conn2

    def test_different_thread_different(self, usage_service):
        main_conn = usage_service._get_conn()
        thread_conn = [None]

        def worker():
            thread_conn[0] = usage_service._get_conn()

        t = threading.Thread(target=worker)
        t.start()
        t.join()

        assert thread_conn[0] is not None
        assert thread_conn[0] is not main_conn
