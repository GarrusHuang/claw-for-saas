"""Tests for agent/session.py — SessionManager (with tenant isolation)."""
import json
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.session import SessionManager

TENANT = "T001"
USER = "U001"


class TestSessionManager:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.sm = SessionManager(base_dir=str(tmp_path / "sessions"))

    def test_create_session(self):
        sid = self.sm.create_session(TENANT, USER)
        assert sid.startswith("sess-")
        assert self.sm.session_exists(TENANT, USER, sid)

    def test_load_empty_session(self):
        sid = self.sm.create_session(TENANT, USER)
        msgs = self.sm.load_messages(TENANT, USER, sid)
        assert msgs == []  # metadata line is filtered out

    def test_append_and_load(self):
        sid = self.sm.create_session(TENANT, USER)
        self.sm.append_message(TENANT, USER, sid, {"role": "user", "content": "hello"})
        self.sm.append_message(TENANT, USER, sid, {"role": "assistant", "content": "hi"})

        msgs = self.sm.load_messages(TENANT, USER, sid)
        assert len(msgs) == 2
        assert msgs[0]["content"] == "hello"
        assert msgs[1]["content"] == "hi"

    def test_load_nonexistent_session(self):
        msgs = self.sm.load_messages(TENANT, USER, "nonexistent")
        assert msgs == []

    def test_delete_session(self):
        sid = self.sm.create_session(TENANT, USER)
        assert self.sm.delete_session(TENANT, USER, sid) is True
        assert self.sm.session_exists(TENANT, USER, sid) is False
        assert self.sm.delete_session(TENANT, USER, sid) is False

    def test_list_sessions(self):
        self.sm.create_session(TENANT, USER)
        self.sm.create_session(TENANT, USER)
        sessions = self.sm.list_sessions(TENANT, USER)
        assert len(sessions) == 2

    def test_list_sessions_empty(self):
        sessions = self.sm.list_sessions(TENANT, "no_user")
        assert sessions == []

    def test_metadata_in_session_list(self):
        sid = self.sm.create_session(TENANT, USER, metadata={"title": "test"})
        sessions = self.sm.list_sessions(TENANT, USER)
        found = [s for s in sessions if s["session_id"] == sid]
        assert len(found) == 1
        assert found[0].get("title") == "test"

    def test_tenant_and_user_isolation(self):
        sid1 = self.sm.create_session("T1", "U1")
        sid2 = self.sm.create_session("T2", "U2")
        self.sm.append_message("T1", "U1", sid1, {"role": "user", "content": "tenant1"})
        self.sm.append_message("T2", "U2", sid2, {"role": "user", "content": "tenant2"})

        msgs1 = self.sm.load_messages("T1", "U1", sid1)
        msgs2 = self.sm.load_messages("T2", "U2", sid2)
        assert msgs1[0]["content"] == "tenant1"
        assert msgs2[0]["content"] == "tenant2"

        # Cross-tenant isolation
        assert self.sm.load_messages("T1", "U1", sid2) == []

    def test_save_and_load_plan_steps(self):
        sid = self.sm.create_session(TENANT, USER)
        steps = [{"action": "step1"}, {"action": "step2"}]
        self.sm.save_plan_steps(TENANT, USER, sid, steps)

        loaded = self.sm.load_plan_steps(TENANT, USER, sid)
        assert loaded == steps

    def test_load_plan_steps_none(self):
        sid = self.sm.create_session(TENANT, USER)
        assert self.sm.load_plan_steps(TENANT, USER, sid) is None

    def test_filters_metadata_and_compaction_marker(self):
        sid = self.sm.create_session(TENANT, USER)
        self.sm.append_message(TENANT, USER, sid, {"type": "compaction_marker", "ts": 0})
        self.sm.append_message(TENANT, USER, sid, {"role": "user", "content": "real msg"})

        msgs = self.sm.load_messages(TENANT, USER, sid)
        assert len(msgs) == 1
        assert msgs[0]["content"] == "real msg"
