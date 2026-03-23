"""
Batch 3 tests: #8 fork 父对话历史, #B spawn_subagents start+wait, #C ToolRegistry 缓存
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from agent.subagent import SubagentRunner
from core.tool_registry import ToolRegistry


def _make_runner():
    llm = MagicMock()
    shared = ToolRegistry()
    capability = ToolRegistry()
    return SubagentRunner(
        llm_client=llm,
        shared_registry=shared,
        capability_registry=capability,
    )


class TestToolRegistryCache:
    """#C: SubagentRunner ToolRegistry 缓存。"""

    def test_merged_registry_cached(self):
        runner = _make_runner()
        reg1 = runner._build_tool_registry("")
        reg2 = runner._build_tool_registry("")
        # 两次调用返回的 all_tools 基础应该是同一个缓存对象
        assert runner._merged_registry_cache is not None

    def test_cache_used_for_whitelist(self):
        runner = _make_runner()
        # 首次调用建立缓存
        runner._build_tool_registry("")
        cache = runner._merged_registry_cache
        # 白名单调用也应使用缓存
        runner._build_tool_registry("nonexistent_tool")
        assert runner._merged_registry_cache is cache


class TestInheritContext:
    """#8: 子 Agent fork 父对话历史。"""

    def test_get_parent_history_returns_none_without_context(self):
        runner = _make_runner()
        result = runner._get_parent_history()
        # 无 RequestContext 时返回 None
        assert result is None

    def test_spawn_subagent_has_inherit_context_param(self):
        """spawn_subagent 工具接受 inherit_context 参数。"""
        from tools.builtin.subagent_tools import spawn_subagent
        import inspect
        sig = inspect.signature(spawn_subagent)
        assert "inherit_context" in sig.parameters


class TestSpawnSubagentsStartWait:
    """#B: spawn_subagents 使用 start+wait 模式。"""

    @pytest.mark.asyncio
    async def test_spawn_subagents_uses_start(self):
        """spawn_subagents 内部调用 start_subagent 而非 run_subagent。"""
        from tools.builtin.subagent_tools import spawn_subagents
        from core.context import RequestContext, current_request

        runner = MagicMock()
        runner.start_subagent = AsyncMock(return_value="sa_abc123")
        runner.wait_subagent = AsyncMock(return_value="结果1")

        ctx = RequestContext(
            subagent_runner=runner,
            user_id="U1",
            subagent_depth=0,
        )
        token = current_request.set(ctx)
        try:
            result = await spawn_subagents(
                tasks='[{"task": "测试任务"}]',
                timeout_s=10,
            )
            # 验证调用了 start_subagent 而非 run_subagent
            runner.start_subagent.assert_called_once()
            runner.wait_subagent.assert_called_once()
            runner.run_subagent.assert_not_called()
            assert "结果1" in result
        finally:
            current_request.set(None)
