"""Tests for SessionManager.cleanup_expired_sessions."""
import json
import sys
import os
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.session import SessionManager

TENANT = "T001"
USER = "U001"


class TestSessionCleanup:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.sm = SessionManager(base_dir=str(tmp_path / "sessions"))
        self.tmp_path = tmp_path

    def _create_session_with_age(self, age_days: float) -> str:
        """Create a session with created_at set to `age_days` days ago."""
        sid = self.sm.create_session(TENANT, USER)
        session_file = self.sm._session_dir(TENANT, USER) / f"{sid}.jsonl"

        # Rewrite the metadata line with a custom created_at
        lines = session_file.read_text(encoding="utf-8").splitlines()
        meta = json.loads(lines[0])
        meta["created_at"] = time.time() - age_days * 86400
        lines[0] = json.dumps(meta, ensure_ascii=False)
        session_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return sid

    def test_expired_session_deleted(self):
        sid = self._create_session_with_age(31)
        deleted = self.sm.cleanup_expired_sessions(retention_days=30)
        assert deleted == 1
        assert not self.sm.session_exists(TENANT, USER, sid)

    def test_recent_session_kept(self):
        sid = self._create_session_with_age(10)
        deleted = self.sm.cleanup_expired_sessions(retention_days=30)
        assert deleted == 0
        assert self.sm.session_exists(TENANT, USER, sid)

    def test_lock_file_removed_with_session(self):
        sid = self._create_session_with_age(31)
        lock_file = self.sm._session_dir(TENANT, USER) / f"{sid}.lock"
        lock_file.touch()
        assert lock_file.exists()

        deleted = self.sm.cleanup_expired_sessions(retention_days=30)
        assert deleted == 1
        assert not lock_file.exists()

    def test_retention_zero_skips_cleanup(self):
        self._create_session_with_age(100)
        deleted = self.sm.cleanup_expired_sessions(retention_days=0)
        assert deleted == 0

    def test_corrupted_file_no_crash(self):
        """Corrupted JSONL files should be skipped without error."""
        sid = self.sm.create_session(TENANT, USER)
        session_file = self.sm._session_dir(TENANT, USER) / f"{sid}.jsonl"
        session_file.write_text("not-valid-json\n", encoding="utf-8")

        deleted = self.sm.cleanup_expired_sessions(retention_days=1)
        assert deleted == 0  # Corrupted file skipped

    def test_mixed_expired_and_recent(self):
        old_sid = self._create_session_with_age(60)
        new_sid = self._create_session_with_age(5)

        deleted = self.sm.cleanup_expired_sessions(retention_days=30)
        assert deleted == 1
        assert not self.sm.session_exists(TENANT, USER, old_sid)
        assert self.sm.session_exists(TENANT, USER, new_sid)

    def test_no_created_at_skipped(self):
        """Sessions without created_at in metadata should be skipped."""
        sid = self.sm.create_session(TENANT, USER)
        session_file = self.sm._session_dir(TENANT, USER) / f"{sid}.jsonl"

        # Remove created_at from metadata
        lines = session_file.read_text(encoding="utf-8").splitlines()
        meta = json.loads(lines[0])
        meta.pop("created_at", None)
        meta["created_at"] = 0  # Explicitly set to 0
        lines[0] = json.dumps(meta, ensure_ascii=False)
        session_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

        deleted = self.sm.cleanup_expired_sessions(retention_days=1)
        assert deleted == 0
