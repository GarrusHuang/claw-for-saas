"""
Tests for AgentGateway._auto_save_memory().

验证: _auto_save_memory 已禁用 — 对话摘要不自动写入 memory，
避免历史对话污染新会话的 system prompt。
用户偏好/修正由 Agent 通过 save_memory 工具主动保存。
"""
from __future__ import annotations

from unittest.mock import MagicMock
from agent.gateway import AgentGateway


def _make_gateway(memory_store=None):
    """创建最小 Gateway 实例。"""
    gw = AgentGateway.__new__(AgentGateway)
    gw.memory_store = memory_store
    return gw


class TestAutoSaveMemoryDisabled:
    """自动记忆保存已禁用 — 不应写入任何内容。"""

    def test_no_write_with_store(self):
        """有 memory_store 时也不应写入。"""
        store = MagicMock()
        gw = _make_gateway(store)

        gw._auto_save_memory(
            tenant_id="t1", user_id="u1",
            message="hello", answer="hi",
        )

        store.write_file.assert_not_called()
        store.read_file.assert_not_called()

    def test_no_crash_without_store(self):
        """没有 memory_store 时不崩溃。"""
        gw = _make_gateway(memory_store=None)
        gw._auto_save_memory(
            tenant_id="t1", user_id="u1",
            message="hello", answer="hi",
        )
