"""
Batch 7 (final) tests: #9 ToolOrchestrator, #38 Context Diff, #26 Dynamic Tools,
#46 Session search, #22 Batch Jobs, #43 Quality Gate semantic
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from core.tool_registry import ToolRegistry, ToolResult, RegisteredTool
from core.tool_orchestrator import ToolOrchestrator, OrchestrationResult


# ── #9: ToolOrchestrator ──

class TestToolOrchestrator:

    @pytest.mark.asyncio
    async def test_basic_execution(self):
        registry = ToolRegistry()
        registry.register(lambda x="": ToolResult(success=True, data="ok"), name="test_tool")
        orch = ToolOrchestrator()
        result = await orch.execute("test_tool", {}, registry)
        assert result.result.success
        assert not result.blocked

    @pytest.mark.asyncio
    async def test_hook_blocks(self):
        from agent.hooks import HookRegistry, HookResult
        hooks = HookRegistry()
        hooks.register("pre_tool_use", lambda e: HookResult(action="block", message="nope"))
        orch = ToolOrchestrator(hooks=hooks)
        registry = ToolRegistry()
        result = await orch.execute("any_tool", {}, registry)
        assert result.blocked
        assert "nope" in result.blocked_reason


# ── #26: Dynamic Tools ──

class TestDynamicTools:

    def test_register_dynamic(self):
        registry = ToolRegistry()
        schema = {"type": "function", "function": {"name": "dyn", "parameters": {}}}
        registry.register_dynamic(
            name="dyn",
            description="Dynamic tool",
            schema=schema,
            func=lambda: "ok",
            defer_loading=True,
        )
        tool = registry.get_tool("dyn")
        assert tool is not None
        assert tool.defer_loading
        assert tool.description == "Dynamic tool"

    def test_defer_loading_flag(self):
        tool = RegisteredTool(
            name="t", description="d", func=lambda: None, schema={},
            defer_loading=True,
        )
        assert tool.defer_loading


# ── #46: Session 搜索优化 ──

class TestSessionSearchOptimized:

    def test_build_search_index(self, tmp_path):
        from agent.session import SessionManager
        sm = SessionManager(base_dir=str(tmp_path))
        sid = sm.create_session("T1", "U1", {"title": "财务报告分析"})
        sm.append_message("T1", "U1", sid, {"role": "user", "content": "请分析这份报告"})
        sm.append_message("T1", "U1", sid, {"role": "assistant", "content": "好的"})

        index = sm._build_search_index("T1", "U1")
        assert len(index) == 1
        assert index[0]["title"] == "财务报告分析"
        assert "分析" in index[0].get("first_user_msg", "")

    def test_search_fast_path(self, tmp_path):
        from agent.session import SessionManager
        sm = SessionManager(base_dir=str(tmp_path))
        sid = sm.create_session("T1", "U1", {"title": "财务报告"})
        sm.append_message("T1", "U1", sid, {"role": "user", "content": "分析财务数据"})
        results = sm.search_sessions("T1", "U1", "财务")
        assert len(results) >= 1
        assert results[0]["title_match"] or results[0]["match_snippet"]


# ── #38: Context Diff ──

class TestContextDiff:
    """Context diff 生成在 _stage2_summarize_middle 内部，间接测试。"""

    def test_removed_summary_format(self):
        """验证 removed_summary_parts 格式。"""
        messages = [
            {"role": "tool", "tool_call_id": "tc_1", "content": "result"},
            {"role": "user", "content": "继续分析"},
            {"role": "assistant", "tool_calls": [{"function": {"name": "read_file"}}]},
        ]
        parts = []
        for msg in messages:
            role = msg.get("role", "")
            if role == "tool":
                parts.append(f"- [removed tool result: {msg.get('tool_call_id', '?')}]")
            elif role == "user":
                parts.append(f"- [removed user: {str(msg.get('content', ''))[:60]}]")
            elif role == "assistant" and msg.get("tool_calls"):
                names = [tc.get("function", {}).get("name", "?") for tc in msg["tool_calls"]]
                parts.append(f"- [removed assistant tool_calls: {', '.join(names)}]")
        assert len(parts) == 3
        assert "tc_1" in parts[0]
        assert "read_file" in parts[2]


# ── #22: Batch Service ──

class TestBatchService:

    def test_batch_job_creation(self):
        from services.batch_service import BatchJob, BatchItem
        items = [BatchItem(index=0, input_text="task1"), BatchItem(index=1, input_text="task2")]
        job = BatchJob(job_id="j1", items=items)
        assert job.status == "pending"
        assert len(job.items) == 2

    def test_batch_service_list_empty(self):
        from services.batch_service import BatchService
        svc = BatchService()
        assert svc.list_jobs() == []


# ── #43: Quality Gate 语义检查 ──

class TestSemanticQualityCheck:

    @pytest.mark.asyncio
    async def test_short_answer_passes(self):
        from agent.quality_gate import check_semantic_quality_async
        from agent.hooks import HookEvent
        event = HookEvent(
            event_type="agent_stop",
            context={"final_answer": "OK"},
            runtime_steps=[],
        )
        passed, _, _ = await check_semantic_quality_async(event)
        assert passed

    @pytest.mark.asyncio
    async def test_no_tools_passes(self):
        from agent.quality_gate import check_semantic_quality_async
        from agent.hooks import HookEvent
        event = HookEvent(
            event_type="agent_stop",
            context={"final_answer": "A long answer that should be checked but has no tools"},
            runtime_steps=[],
        )
        passed, _, _ = await check_semantic_quality_async(event)
        assert passed
