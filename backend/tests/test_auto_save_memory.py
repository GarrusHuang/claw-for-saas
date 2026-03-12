"""
Tests for AgentGateway._auto_save_memory().

验证 OpenClaw 模式的自动会话记忆保存:
1. 每次对话保存摘要到 conversations.md
2. 超过条数限制时自动裁剪
3. 无 memory_store / 异常时不崩溃
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock
from agent.gateway import AgentGateway


def _make_gateway(memory_store=None):
    """创建最小 Gateway 实例。"""
    gw = AgentGateway.__new__(AgentGateway)
    gw.memory_store = memory_store
    return gw


class TestAutoSaveMemory:
    """自动记忆保存测试。"""

    def test_saves_conversation_summary(self):
        """每次对话应保存用户消息 + 回复摘要。"""
        store = MagicMock()
        store.read_file.return_value = ""
        store.write_file.return_value = True
        gw = _make_gateway(store)

        gw._auto_save_memory(
            tenant_id="t1", user_id="u1",
            message="我叫妞妞，请记住我的名字",
            answer="好的，妞妞！我会记住的。",
        )

        # 应该调用 write_file 写入 conversations.md
        write_calls = store.write_file.call_args_list
        assert len(write_calls) >= 1

        # 找到 conversations.md 的写入
        conv_call = next(
            c for c in write_calls
            if c.kwargs.get("filename") == "conversations.md"
        )
        assert "我叫妞妞" in conv_call.kwargs["content"]
        assert "妞妞" in conv_call.kwargs["content"]
        assert conv_call.kwargs["mode"] == "append"
        assert conv_call.kwargs["scope"] == "user"

    def test_truncates_long_messages(self):
        """超长消息应被截断到 200 字。"""
        store = MagicMock()
        store.read_file.return_value = ""
        store.write_file.return_value = True
        gw = _make_gateway(store)

        long_msg = "A" * 500
        gw._auto_save_memory(
            tenant_id="t1", user_id="u1",
            message=long_msg,
            answer="ok",
        )

        conv_call = next(
            c for c in store.write_file.call_args_list
            if c.kwargs.get("filename") == "conversations.md"
        )
        # 用户消息部分不应超过 200 字
        content = conv_call.kwargs["content"]
        user_line = [l for l in content.split("\n") if l.startswith("- 用户:")][0]
        assert len(user_line) <= 210  # "- 用户: " + 200 chars

    def test_trims_when_exceeds_max_entries(self):
        """超过最大条数限制时应裁剪。"""
        store = MagicMock()
        # 模拟已有 25 条记录 (超过 _MAX_CONVERSATION_ENTRIES=20)
        entries = [f"### 2026-03-{i:02d} 10:00\n- 用户: msg{i}\n- 回复: ans{i}\n"
                   for i in range(1, 26)]
        existing_content = "\n".join(entries)
        store.read_file.return_value = existing_content
        store.write_file.return_value = True
        gw = _make_gateway(store)

        gw._auto_save_memory(
            tenant_id="t1", user_id="u1",
            message="new message",
            answer="new answer",
        )

        # 应有 rewrite 调用来裁剪
        rewrite_calls = [
            c for c in store.write_file.call_args_list
            if c.kwargs.get("mode") == "rewrite"
        ]
        assert len(rewrite_calls) == 1
        # 裁剪后内容应以 "### " 开头
        trimmed = rewrite_calls[0].kwargs["content"]
        assert trimmed.startswith("### ")

    def test_no_trim_when_under_limit(self):
        """未超限时不应裁剪。"""
        store = MagicMock()
        store.read_file.return_value = "### 2026-03-01\n- 用户: hi\n- 回复: hello\n"
        store.write_file.return_value = True
        gw = _make_gateway(store)

        gw._auto_save_memory(
            tenant_id="t1", user_id="u1",
            message="how are you",
            answer="fine",
        )

        rewrite_calls = [
            c for c in store.write_file.call_args_list
            if c.kwargs.get("mode") == "rewrite"
        ]
        assert len(rewrite_calls) == 0

    def test_no_crash_without_memory_store(self):
        """没有 memory_store 时不应崩溃。"""
        gw = _make_gateway(memory_store=None)
        gw._auto_save_memory(
            tenant_id="t1", user_id="u1",
            message="hello", answer="hi",
        )

    def test_no_crash_on_write_error(self):
        """store 写入失败时不应崩溃。"""
        store = MagicMock()
        store.write_file.side_effect = Exception("disk full")
        gw = _make_gateway(store)

        gw._auto_save_memory(
            tenant_id="t1", user_id="u1",
            message="hello", answer="hi",
        )

    def test_no_crash_on_read_error(self):
        """store 读取失败时不应崩溃。"""
        store = MagicMock()
        store.write_file.return_value = True
        store.read_file.side_effect = Exception("io error")
        gw = _make_gateway(store)

        gw._auto_save_memory(
            tenant_id="t1", user_id="u1",
            message="hello", answer="hi",
        )

    def test_passes_correct_tenant_user(self):
        """应将 tenant_id 和 user_id 正确传递给 store。"""
        store = MagicMock()
        store.read_file.return_value = ""
        store.write_file.return_value = True
        gw = _make_gateway(store)

        gw._auto_save_memory(
            tenant_id="acme", user_id="alice",
            message="hi", answer="hello",
        )

        call = store.write_file.call_args_list[0]
        assert call.kwargs["tenant_id"] == "acme"
        assert call.kwargs["user_id"] == "alice"

    def test_newlines_in_message_replaced(self):
        """消息中的换行符应被替换为空格。"""
        store = MagicMock()
        store.read_file.return_value = ""
        store.write_file.return_value = True
        gw = _make_gateway(store)

        gw._auto_save_memory(
            tenant_id="t1", user_id="u1",
            message="line1\nline2\nline3",
            answer="resp1\nresp2",
        )

        call = store.write_file.call_args_list[0]
        content = call.kwargs["content"]
        user_line = [l for l in content.split("\n") if l.startswith("- 用户:")][0]
        assert "\n" not in user_line.replace("- 用户: ", "")

    def test_empty_answer_handled(self):
        """空回复不应崩溃。"""
        store = MagicMock()
        store.read_file.return_value = ""
        store.write_file.return_value = True
        gw = _make_gateway(store)

        gw._auto_save_memory(
            tenant_id="t1", user_id="u1",
            message="hello", answer="",
        )

        call = store.write_file.call_args_list[0]
        assert "conversations.md" in str(call)
