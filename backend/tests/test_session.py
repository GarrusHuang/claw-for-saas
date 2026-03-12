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

    # ── Search ──

    def test_search_by_title(self):
        self.sm.create_session(TENANT, USER, metadata={"title": "报销审核"})
        self.sm.create_session(TENANT, USER, metadata={"title": "合同起草"})

        results = self.sm.search_sessions(TENANT, USER, "报销")
        assert len(results) == 1
        assert results[0]["title"] == "报销审核"
        assert results[0]["title_match"] is True

    def test_search_by_message_content(self):
        sid = self.sm.create_session(TENANT, USER, metadata={"title": "对话"})
        self.sm.append_message(TENANT, USER, sid, {
            "role": "user", "content": "请帮我查一下发票信息"
        })

        results = self.sm.search_sessions(TENANT, USER, "发票")
        assert len(results) == 1
        assert "发票" in results[0]["match_snippet"]

    def test_search_empty_query_returns_empty(self):
        self.sm.create_session(TENANT, USER, metadata={"title": "test"})
        assert self.sm.search_sessions(TENANT, USER, "") == []
        assert self.sm.search_sessions(TENANT, USER, "   ") == []

    def test_search_no_match(self):
        self.sm.create_session(TENANT, USER, metadata={"title": "报销"})
        results = self.sm.search_sessions(TENANT, USER, "zzz_not_found")
        assert results == []

    def test_search_case_insensitive(self):
        sid = self.sm.create_session(TENANT, USER)
        self.sm.append_message(TENANT, USER, sid, {
            "role": "user", "content": "Hello World test"
        })
        results = self.sm.search_sessions(TENANT, USER, "hello")
        assert len(results) == 1

    def test_search_respects_limit(self):
        for i in range(5):
            self.sm.create_session(TENANT, USER, metadata={"title": f"会话{i}"})
        results = self.sm.search_sessions(TENANT, USER, "会话", limit=3)
        assert len(results) == 3

    def test_search_snippet_context(self):
        sid = self.sm.create_session(TENANT, USER)
        self.sm.append_message(TENANT, USER, sid, {
            "role": "user", "content": "前面的文字" + "x" * 50 + "关键词在这里" + "y" * 80 + "后面文字"
        })
        results = self.sm.search_sessions(TENANT, USER, "关键词")
        assert len(results) == 1
        snippet = results[0]["match_snippet"]
        assert "关键词" in snippet
        assert "..." in snippet  # 截断标志

    def test_search_tenant_isolation(self):
        self.sm.create_session("T1", USER, metadata={"title": "T1的会话"})
        self.sm.create_session("T2", USER, metadata={"title": "T2的会话"})

        results = self.sm.search_sessions("T1", USER, "会话")
        assert len(results) == 1
        assert results[0]["title"] == "T1的会话"

    # ── A5: compact 原子写 ──

    def test_compact_atomic_write_no_temp_files(self):
        """compact 完成后不应残留 .tmp 文件 (A5: 原子写)。"""
        import asyncio

        sid = self.sm.create_session(TENANT, USER)
        # 写入足够多消息以触发压缩 (需 > max_recent*2 = 12)
        for i in range(14):
            self.sm.append_message(TENANT, USER, sid, {
                "role": "user" if i % 2 == 0 else "assistant",
                "content": f"message {i}",
            })

        # Mock LLM client
        class FakeLLM:
            async def chat_completion(self, **kwargs):
                class R:
                    content = "压缩摘要"
                return R()

        session_dir = self.sm._session_dir(TENANT, USER)
        asyncio.get_event_loop().run_until_complete(
            self.sm.compact(TENANT, USER, sid, FakeLLM(), max_recent=6)
        )

        # 验证: 无 .tmp 残留
        tmp_files = list(session_dir.glob("*.tmp"))
        assert tmp_files == []
        # 验证: session 文件存在且可读
        msgs = self.sm.load_messages(TENANT, USER, sid)
        assert len(msgs) > 0

    def test_compact_preserves_recent_messages(self):
        """compact 应保留最近 max_recent 条消息 (A5)。"""
        import asyncio

        sid = self.sm.create_session(TENANT, USER)
        for i in range(14):
            self.sm.append_message(TENANT, USER, sid, {
                "role": "user" if i % 2 == 0 else "assistant",
                "content": f"msg-{i}",
            })

        class FakeLLM:
            async def chat_completion(self, **kwargs):
                class R:
                    content = "compressed history"
                return R()

        asyncio.get_event_loop().run_until_complete(
            self.sm.compact(TENANT, USER, sid, FakeLLM(), max_recent=4)
        )

        msgs = self.sm.load_messages(TENANT, USER, sid)
        contents = [m.get("content", "") for m in msgs]
        # 应包含摘要
        assert any("compressed history" in c for c in contents)
        # 最后一条消息应保留
        assert "msg-13" in contents
