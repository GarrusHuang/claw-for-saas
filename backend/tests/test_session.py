"""Tests for agent/session.py — SessionManager."""
import json
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.session import SessionManager


class TestSessionManager:
    def setup_method(self, tmp_path=None):
        pass

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.sm = SessionManager(base_dir=str(tmp_path / "sessions"))

    def test_create_session(self):
        sid = self.sm.create_session("U001")
        assert sid.startswith("sess-")
        assert self.sm.session_exists("U001", sid)

    def test_load_empty_session(self):
        sid = self.sm.create_session("U001")
        msgs = self.sm.load_messages("U001", sid)
        assert msgs == []  # metadata line is filtered out

    def test_append_and_load(self):
        sid = self.sm.create_session("U001")
        self.sm.append_message("U001", sid, {"role": "user", "content": "hello"})
        self.sm.append_message("U001", sid, {"role": "assistant", "content": "hi"})

        msgs = self.sm.load_messages("U001", sid)
        assert len(msgs) == 2
        assert msgs[0]["content"] == "hello"
        assert msgs[1]["content"] == "hi"

    def test_load_nonexistent_session(self):
        msgs = self.sm.load_messages("U001", "nonexistent")
        assert msgs == []

    def test_delete_session(self):
        sid = self.sm.create_session("U001")
        assert self.sm.delete_session("U001", sid) is True
        assert self.sm.session_exists("U001", sid) is False
        assert self.sm.delete_session("U001", sid) is False

    def test_list_sessions(self):
        self.sm.create_session("U001")
        self.sm.create_session("U001")
        sessions = self.sm.list_sessions("U001")
        assert len(sessions) == 2

    def test_list_sessions_empty(self):
        sessions = self.sm.list_sessions("no_user")
        assert sessions == []

    def test_metadata_in_session_list(self):
        sid = self.sm.create_session("U001", metadata={"title": "test"})
        sessions = self.sm.list_sessions("U001")
        found = [s for s in sessions if s["session_id"] == sid]
        assert len(found) == 1
        assert found[0].get("title") == "test"

    def test_user_isolation(self):
        sid1 = self.sm.create_session("U001")
        sid2 = self.sm.create_session("U002")
        self.sm.append_message("U001", sid1, {"role": "user", "content": "user1"})
        self.sm.append_message("U002", sid2, {"role": "user", "content": "user2"})

        msgs1 = self.sm.load_messages("U001", sid1)
        msgs2 = self.sm.load_messages("U002", sid2)
        assert msgs1[0]["content"] == "user1"
        assert msgs2[0]["content"] == "user2"

    def test_save_and_load_plan_steps(self):
        sid = self.sm.create_session("U001")
        steps = [{"action": "step1"}, {"action": "step2"}]
        self.sm.save_plan_steps("U001", sid, steps)

        loaded = self.sm.load_plan_steps("U001", sid)
        assert loaded == steps

    def test_load_plan_steps_none(self):
        sid = self.sm.create_session("U001")
        assert self.sm.load_plan_steps("U001", sid) is None

    def test_filters_metadata_and_compaction_marker(self):
        sid = self.sm.create_session("U001")
        # Manually append special entries
        self.sm.append_message("U001", sid, {"type": "compaction_marker", "ts": 0})
        self.sm.append_message("U001", sid, {"role": "user", "content": "real msg"})

        msgs = self.sm.load_messages("U001", sid)
        assert len(msgs) == 1
        assert msgs[0]["content"] == "real msg"
