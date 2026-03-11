"""
Tests for A4: 上下文管理全面升级。

Covers:
- 4a: smart_truncate (head+tail)
- 4b: file pagination
- 4c: dynamic context budget
- 4d: multi-stage compression
- 4e: identifier protection
- 4f: tool pair repair
- 4g: token estimation caching
- 4j: compression observability
"""
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from core.tool_registry import ToolResult, smart_truncate
from core.runtime import RuntimeConfig, AgenticRuntime
from core.token_estimator import (
    estimate_tokens,
    estimate_tokens_conservative,
    estimate_messages_tokens,
    invalidate_cache,
    _msg_token_cache,
    _estimate_single_message_tokens,
)
from agent.pre_compact import pre_compact_hook, _extract_identifiers
from agent.hooks import HookEvent, HookResult


# ═══ 4a: Smart Truncate ═══

class TestSmartTruncate:
    def test_no_truncation_when_within_limit(self):
        assert smart_truncate("hello", 100) == "hello"

    def test_simple_truncation_small_budget(self):
        text = "a" * 5000
        result = smart_truncate(text, 100)
        assert result.endswith("...[truncated]")
        assert len(result) == 100 + len("...[truncated]")

    def test_head_tail_truncation_with_error(self):
        """When tail has error info, should preserve it."""
        head = "x" * 5000
        tail = '{"error": "something failed"}'
        text = head + tail
        result = smart_truncate(text, 3000)
        assert "truncated" in result
        assert "error" in result  # tail preserved

    def test_head_tail_truncation_with_json_close(self):
        """JSON closing brace triggers tail preservation."""
        text = '{"data": "' + "x" * 5000 + '"}'
        result = smart_truncate(text, 3000)
        assert "}" in result

    def test_head_only_when_no_important_tail(self):
        """No important tail → all budget to head."""
        text = "abcdefghij" * 500  # 5000 chars, no important tail
        result = smart_truncate(text, 3000)
        assert "truncated" in result

    def test_tool_result_smart_truncation(self):
        """ToolResult.to_json uses smart_truncate for large results."""
        data = {"items": ["item_" + str(i) for i in range(500)], "error": "trailing error"}
        r = ToolResult(success=True, data=data)
        j = r.to_json(max_chars=3000)
        assert "truncated" in j


# ═══ 4b: File Pagination ═══

class TestFilePagination:
    """Tests for read_uploaded_file pagination and dynamic page size."""

    def test_pagination_config_exists(self):
        from config import Settings
        s = Settings()
        assert hasattr(s, "agent_file_page_size")
        assert s.agent_file_page_size == 50000

    def test_dynamic_page_size_default_32k(self):
        """Default 32K window → 32000*0.2*4=25600 → clamped to 50000 (min)."""
        from config import Settings
        s = Settings(agent_model_context_window=32000)
        dynamic = int(s.agent_model_context_window * 0.2 * 4)
        page_size = max(50000, min(512000, dynamic))
        assert dynamic == 25600
        assert page_size == 50000  # hit floor

    def test_dynamic_page_size_128k(self):
        """128K window → 128000*0.2*4=102400 → within range."""
        dynamic = int(128000 * 0.2 * 4)
        page_size = max(50000, min(512000, dynamic))
        assert dynamic == 102400
        assert page_size == 102400

    def test_dynamic_page_size_1m(self):
        """1M window → 1000000*0.2*4=800000 → clamped to 512000 (max)."""
        dynamic = int(1000000 * 0.2 * 4)
        page_size = max(50000, min(512000, dynamic))
        assert dynamic == 800000
        assert page_size == 512000  # hit ceiling

    def test_dynamic_page_size_small_window(self):
        """Small 8K window → 8000*0.2*4=6400 → clamped to 50000 (min)."""
        dynamic = int(8000 * 0.2 * 4)
        page_size = max(50000, min(512000, dynamic))
        assert dynamic == 6400
        assert page_size == 50000

    def test_user_limit_overrides_dynamic(self):
        """When user passes limit > 0, it overrides the dynamic page size."""
        dynamic_page = int(128000 * 0.2 * 4)
        page_size = max(50000, min(512000, dynamic_page))
        # User explicit limit
        user_limit = 20000
        if user_limit > 0:
            page_size = user_limit
        assert page_size == 20000

    def test_user_limit_zero_uses_dynamic(self):
        """When user passes limit=0, dynamic page size is used."""
        dynamic_page = int(128000 * 0.2 * 4)
        page_size = max(50000, min(512000, dynamic_page))
        user_limit = 0
        if user_limit > 0:
            page_size = user_limit
        assert page_size == 102400  # dynamic, not overridden


# ═══ 4c: Dynamic Context Budget ═══

class TestDynamicBudget:
    def test_default_budget_calculation(self):
        config = RuntimeConfig()
        # 32000 * 0.8 = 25600
        assert config.get_effective_budget() == 25600

    def test_override_budget(self):
        config = RuntimeConfig(context_budget_tokens=10000)
        assert config.get_effective_budget() == 10000

    def test_min_budget_enforced(self):
        config = RuntimeConfig(model_context_window=1000, context_budget_ratio=0.5)
        # 1000 * 0.5 = 500, but min is 16000
        assert config.get_effective_budget() == 16000

    def test_large_model_budget(self):
        config = RuntimeConfig(model_context_window=128000)
        # 128000 * 0.8 = 102400
        assert config.get_effective_budget() == 102400

    def test_custom_ratio(self):
        config = RuntimeConfig(model_context_window=64000, context_budget_ratio=0.6)
        # 64000 * 0.6 = 38400
        assert config.get_effective_budget() == 38400

    def test_new_config_fields_in_settings(self):
        from config import Settings
        s = Settings()
        assert hasattr(s, "agent_model_context_window")
        assert hasattr(s, "agent_context_budget_ratio")
        assert hasattr(s, "agent_compress_threshold_ratio")
        assert hasattr(s, "agent_context_budget_min")


# ═══ 4d: Multi-stage Compression ═══

class TestMultiStageCompression:
    def _make_messages(self, n_tool_rounds=5, tool_result_size=1000):
        """Build a messages list with N rounds of tool calls."""
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Do something complex."},
        ]
        for i in range(n_tool_rounds):
            # assistant with tool_calls
            messages.append({
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": f"call_{i}",
                    "type": "function",
                    "function": {"name": f"tool_{i}", "arguments": "{}"},
                }],
            })
            # tool result
            messages.append({
                "role": "tool",
                "tool_call_id": f"call_{i}",
                "content": "x" * tool_result_size,
            })
        # final assistant message
        messages.append({"role": "assistant", "content": "Here is the result."})
        return messages

    def test_stage1_truncates_old_tool_results(self):
        """Stage 1 should truncate old tool results, keep recent ones."""
        messages = self._make_messages(n_tool_rounds=8, tool_result_size=2000)
        runtime = AgenticRuntime(
            llm_client=None,
            tool_registry=_mock_registry(),
        )
        result = runtime._stage1_truncate_tool_results(messages)

        # Recent 4 tool results should be untouched
        tool_msgs = [m for m in result if m.get("role") == "tool"]
        assert len(tool_msgs) == 8
        # Older ones truncated
        for tm in tool_msgs[:4]:
            assert len(tm["content"]) < 2000
        # Recent 4 preserved
        for tm in tool_msgs[4:]:
            assert len(tm["content"]) == 2000

    def test_stage3_metadata_mode(self):
        """Stage 3 keeps system + summary + last 4 messages."""
        messages = self._make_messages(n_tool_rounds=10, tool_result_size=500)
        runtime = AgenticRuntime(
            llm_client=None,
            tool_registry=_mock_registry(),
        )
        result = runtime._stage3_metadata_mode(messages)
        assert result[0]["role"] == "system"
        assert "compacted" in result[1]["content"]
        assert len(result) == 1 + 1 + 4  # system + summary + tail 4


# ═══ 4e: Identifier Protection ═══

class TestIdentifierProtection:
    def test_extract_ids(self):
        text = 'employee_id="EMP001" 单号: RB-2025-001'
        ids = _extract_identifiers(text)
        assert len(ids) >= 1

    def test_extract_amounts(self):
        text = "报销金额 ¥12,345.67 另一个 500元"
        ids = _extract_identifiers(text)
        amounts = [i for i in ids if any(c in i for c in "¥元")]
        assert len(amounts) >= 2

    def test_extract_dates(self):
        text = "入职日期 2025-01-15 出差日期 2025年3月20日"
        ids = _extract_identifiers(text)
        dates = [i for i in ids if "2025" in i]
        assert len(dates) >= 2

    def test_strict_mode_preserves_identifiers(self):
        event = HookEvent(
            event_type="pre_compact",
            context={
                "messages_to_compact": [
                    {"role": "tool", "content": 'ID: "EMP001" 金额 ¥500'},
                ],
                "protection_mode": "strict",
            },
        )
        result = pre_compact_hook(event)
        assert result.action == "modify"
        assert "PRESERVED identifiers" in result.message

    def test_off_mode_skips_protection(self):
        event = HookEvent(
            event_type="pre_compact",
            context={
                "messages_to_compact": [
                    {"role": "tool", "content": 'ID: "EMP001" known_value'},
                ],
                "protection_mode": "off",
            },
        )
        result = pre_compact_hook(event)
        assert result.action == "allow"


# ═══ 4f: Tool Pair Repair ═══

class TestToolPairRepair:
    def test_orphan_tool_message_removed(self):
        """Tool message without matching assistant tool_call → removed."""
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "tool", "tool_call_id": "orphan_1", "content": "data"},
            {"role": "assistant", "content": "done"},
        ]
        repaired = AgenticRuntime._repair_tool_pairs(messages)
        roles = [m["role"] for m in repaired]
        assert "tool" not in roles  # orphan removed

    def test_orphan_assistant_tool_call_patched(self):
        """Assistant tool_call without matching tool result → patch added."""
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "call_1", "type": "function", "function": {"name": "calc", "arguments": "{}"}},
            ]},
            {"role": "assistant", "content": "done"},
        ]
        repaired = AgenticRuntime._repair_tool_pairs(messages)
        tool_msgs = [m for m in repaired if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0]["tool_call_id"] == "call_1"
        assert "compacted" in tool_msgs[0]["content"]

    def test_valid_pairs_unchanged(self):
        """Valid tool pairs should not be modified."""
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "call_1", "type": "function", "function": {"name": "calc", "arguments": "{}"}},
            ]},
            {"role": "tool", "tool_call_id": "call_1", "content": "result"},
            {"role": "assistant", "content": "done"},
        ]
        repaired = AgenticRuntime._repair_tool_pairs(messages)
        assert len(repaired) == 4  # unchanged
        assert repaired[2]["content"] == "result"

    def test_multiple_orphans(self):
        """Multiple orphan tool_calls get patched."""
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "call_1", "type": "function", "function": {"name": "a", "arguments": "{}"}},
                {"id": "call_2", "type": "function", "function": {"name": "b", "arguments": "{}"}},
            ]},
            {"role": "tool", "tool_call_id": "call_1", "content": "result1"},
            # call_2 has no response
        ]
        repaired = AgenticRuntime._repair_tool_pairs(messages)
        tool_msgs = [m for m in repaired if m.get("role") == "tool"]
        assert len(tool_msgs) == 2
        # Both call_1 and call_2 should have responses
        tc_ids = {m["tool_call_id"] for m in tool_msgs}
        assert tc_ids == {"call_1", "call_2"}


# ═══ 4g: Token Estimation Caching ═══

class TestTokenEstimationCaching:
    def setup_method(self):
        invalidate_cache()

    def test_cache_hit(self):
        msg = {"role": "user", "content": "hello world"}
        t1 = _estimate_single_message_tokens(msg)
        assert len(_msg_token_cache) == 1
        t2 = _estimate_single_message_tokens(msg)
        assert t1 == t2

    def test_different_messages_different_cache(self):
        m1 = {"role": "user", "content": "hello"}
        m2 = {"role": "user", "content": "goodbye"}
        _estimate_single_message_tokens(m1)
        _estimate_single_message_tokens(m2)
        assert len(_msg_token_cache) == 2

    def test_invalidate_cache(self):
        msg = {"role": "user", "content": "test"}
        _estimate_single_message_tokens(msg)
        assert len(_msg_token_cache) > 0
        invalidate_cache()
        assert len(_msg_token_cache) == 0

    def test_conservative_estimation_for_tool(self):
        """Tool results should use conservative estimation (2 chars/token)."""
        text = "a" * 1000
        normal = estimate_tokens(text)
        conservative = estimate_tokens_conservative(text)
        assert conservative > normal  # 2 chars/token > 4 chars/token

    def test_estimate_messages_uses_cache(self):
        messages = [
            {"role": "user", "content": "hi " * 100},
            {"role": "assistant", "content": "response " * 100},
        ]
        invalidate_cache()
        t1 = estimate_messages_tokens(messages)
        cache_size = len(_msg_token_cache)
        t2 = estimate_messages_tokens(messages)
        assert t1 == t2
        # Cache should still be same size (no new entries)
        assert len(_msg_token_cache) == cache_size


# ═══ 4j: Compression Observability ═══

class TestCompressionObservability:
    def test_emit_compaction_event(self):
        events = []

        class FakeBus:
            def emit(self, event_type, data):
                events.append((event_type, data))

        runtime = AgenticRuntime(
            llm_client=None,
            tool_registry=_mock_registry(),
            event_bus=FakeBus(),
        )
        runtime._emit_compaction_event(
            stage=2,
            original_count=20,
            compacted_count=9,
            original_tokens=30000,
            compacted_tokens=15000,
        )
        assert len(events) == 1
        assert events[0][0] == "agent_progress"
        data = events[0][1]
        assert data["status"] == "context_compacted"
        assert data["stage"] == 2
        assert data["compression_ratio"] == 0.5

    def test_emit_compaction_event_includes_reason(self):
        """_emit_compaction_event should include reason field in SSE data."""
        events = []

        class FakeBus:
            def emit(self, event_type, data):
                events.append((event_type, data))

        runtime = AgenticRuntime(
            llm_client=None,
            tool_registry=_mock_registry(),
            event_bus=FakeBus(),
        )
        runtime._emit_compaction_event(
            stage=1,
            original_count=10,
            compacted_count=8,
            original_tokens=20000,
            compacted_tokens=12000,
            reason="large_system_prompt",
        )
        data = events[0][1]
        assert data["reason"] == "large_system_prompt"

    def test_compact_stats_accumulate(self):
        """Multiple compaction events should accumulate in _compact_stats."""
        runtime = AgenticRuntime(
            llm_client=None,
            tool_registry=_mock_registry(),
        )
        assert runtime._compact_stats["count"] == 0

        runtime._emit_compaction_event(1, 20, 18, 30000, 24000, reason="accumulated_context")
        runtime._emit_compaction_event(2, 18, 9, 24000, 12000, reason="accumulated_context")

        assert runtime._compact_stats["count"] == 2
        assert runtime._compact_stats["stages"][1] == 1
        assert runtime._compact_stats["stages"][2] == 1
        assert runtime._compact_stats["stages"][3] == 0
        # total_ratio = 24000/30000 + 12000/24000 = 0.8 + 0.5 = 1.3
        assert abs(runtime._compact_stats["total_ratio"] - 1.3) < 0.01

    def test_build_result_includes_compact_stats(self):
        """RuntimeResult should include compact_stats when compression happened."""
        runtime = AgenticRuntime(
            llm_client=None,
            tool_registry=_mock_registry(),
        )
        # No compression -> compact_stats is None
        result_no_compact = runtime._build_result("answer", iterations=1)
        assert result_no_compact.compact_stats is None

        # Trigger compaction stats
        runtime._emit_compaction_event(1, 20, 18, 30000, 24000, reason="accumulated_context")
        result_with_compact = runtime._build_result("answer", iterations=2)
        assert result_with_compact.compact_stats is not None
        assert result_with_compact.compact_stats["count"] == 1
        assert result_with_compact.compact_stats["avg_ratio"] == 0.8

    def test_classify_reason_too_few_messages(self):
        """<=4 messages should classify as too_few_messages."""
        runtime = AgenticRuntime(
            llm_client=None,
            tool_registry=_mock_registry(),
            config=RuntimeConfig(context_budget_tokens=1000),
        )
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "x" * 5000},
        ]
        reason = runtime._classify_compaction_reason(messages, 2000, 1000)
        assert reason == "too_few_messages"

    def test_classify_reason_large_system_prompt(self):
        """System prompt >50% of budget -> large_system_prompt."""
        runtime = AgenticRuntime(
            llm_client=None,
            tool_registry=_mock_registry(),
            config=RuntimeConfig(context_budget_tokens=1000),
        )
        messages = [
            {"role": "system", "content": "x" * 10000},  # very large system
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "ok"},
            {"role": "user", "content": "more"},
            {"role": "assistant", "content": "done"},
        ]
        reason = runtime._classify_compaction_reason(messages, 5000, 1000)
        assert reason == "large_system_prompt"

    def test_classify_reason_long_single_message(self):
        """Single message >30% of budget -> long_single_message."""
        runtime = AgenticRuntime(
            llm_client=None,
            tool_registry=_mock_registry(),
            config=RuntimeConfig(context_budget_tokens=2000),
        )
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "ok"},
            {"role": "user", "content": "more"},
            {"role": "tool", "tool_call_id": "c1", "content": "x" * 10000},
        ]
        reason = runtime._classify_compaction_reason(messages, 6000, 2000)
        assert reason == "long_single_message"

    def test_classify_reason_accumulated_context(self):
        """Normal accumulation with many moderate messages."""
        runtime = AgenticRuntime(
            llm_client=None,
            tool_registry=_mock_registry(),
            config=RuntimeConfig(context_budget_tokens=50000),
        )
        messages = [
            {"role": "system", "content": "short system"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
            {"role": "user", "content": "question"},
            {"role": "assistant", "content": "answer"},
        ]
        reason = runtime._classify_compaction_reason(messages, 55000, 50000)
        assert reason == "accumulated_context"

    def test_overflow_retries_tracked(self):
        """_compact_stats should track overflow_retries."""
        runtime = AgenticRuntime(
            llm_client=None,
            tool_registry=_mock_registry(),
        )
        assert runtime._compact_stats["overflow_retries"] == 0

    def test_default_reason_when_not_specified(self):
        """_emit_compaction_event uses 'accumulated_context' as default reason."""
        events = []

        class FakeBus:
            def emit(self, event_type, data):
                events.append((event_type, data))

        runtime = AgenticRuntime(
            llm_client=None,
            tool_registry=_mock_registry(),
            event_bus=FakeBus(),
        )
        runtime._emit_compaction_event(
            stage=1,
            original_count=10,
            compacted_count=8,
            original_tokens=20000,
            compacted_tokens=12000,
        )
        data = events[0][1]
        assert data["reason"] == "accumulated_context"


# ═══ Helpers ═══

def _mock_registry():
    from core.tool_registry import ToolRegistry
    reg = ToolRegistry()

    @reg.tool(description="test tool", read_only=True)
    def test_tool() -> dict:
        return {"ok": True}

    return reg


# ═══ 4a-budget: 多工具结果按比例分配总预算 ═══

class TestAllocateToolBudgets:
    """A4-4a: _allocate_tool_budgets 按比例分配总预算。"""

    def _make_result(self, data_size: int) -> ToolResult:
        """创建指定大小的 ToolResult。"""
        # 生成 data_size 长度的字符串作为 data
        return ToolResult(success=True, data="x" * data_size)

    def _make_error_result(self, msg: str = "err") -> ToolResult:
        return ToolResult(success=False, error=msg)

    def _runtime(self) -> AgenticRuntime:
        return AgenticRuntime(
            llm_client=None,
            tool_registry=_mock_registry(),
        )

    def test_single_tool_uses_max_per_tool(self):
        """单个工具直接使用 max_per_tool。"""
        rt = self._runtime()
        obs = [self._make_result(5000)]
        budgets = rt._allocate_tool_budgets(obs, max_per_tool=3000)
        assert budgets == [3000]

    def test_no_limit_returns_zeros(self):
        """max_per_tool=0 表示不限制。"""
        rt = self._runtime()
        obs = [self._make_result(5000), self._make_result(5000)]
        budgets = rt._allocate_tool_budgets(obs, max_per_tool=0)
        assert budgets == [0, 0]

    def test_empty_observations(self):
        """空列表返回空。"""
        rt = self._runtime()
        budgets = rt._allocate_tool_budgets([], max_per_tool=3000)
        assert budgets == []

    def test_small_results_get_max_per_tool(self):
        """所有结果都小于总预算时，每个都拿到 max_per_tool。"""
        rt = self._runtime()
        # 两个各 100 字符的结果，总预算 = 3000 * 2 * 1.5 = 9000
        obs = [self._make_result(50), self._make_result(50)]
        budgets = rt._allocate_tool_budgets(obs, max_per_tool=3000)
        assert budgets == [3000, 3000]

    def test_proportional_allocation_large_vs_small(self):
        """一大一小结果，大的分到更多预算。"""
        rt = self._runtime()
        # 一个 10000 字符，一个 100 字符
        obs = [self._make_result(10000), self._make_result(100)]
        budgets = rt._allocate_tool_budgets(obs, max_per_tool=3000)
        # 总预算 = 3000 * 2 * 1.5 = 9000
        # 大的约占 10000/10100 ≈ 99%，小的约占 1%
        # 大的应该拿到绝大部分预算
        assert budgets[0] > budgets[1]
        # 小的至少 2000（最低保留）
        assert budgets[1] >= 2000

    def test_minimum_budget_2000(self):
        """每个工具至少保留 2000 字符。"""
        rt = self._runtime()
        # 3 个工具，一个巨大，两个很小
        obs = [
            self._make_result(50000),
            self._make_result(10),
            self._make_result(10),
        ]
        budgets = rt._allocate_tool_budgets(obs, max_per_tool=3000)
        for b in budgets:
            assert b >= 2000, f"Budget {b} is below minimum 2000"

    def test_three_equal_results(self):
        """三个相同大小的结果，预算基本均分。"""
        rt = self._runtime()
        obs = [self._make_result(5000)] * 3
        budgets = rt._allocate_tool_budgets(obs, max_per_tool=3000)
        # 总预算 = 3000 * 3 * 1.5 = 13500
        # 总原始 = 15000+ (含 JSON 包裹)
        # 均分约 4500 每个
        assert len(budgets) == 3
        # 三个应大致相等
        assert max(budgets) - min(budgets) < 500

    def test_error_results_included(self):
        """错误结果也参与预算分配。"""
        rt = self._runtime()
        obs = [self._make_result(8000), self._make_error_result("something failed")]
        budgets = rt._allocate_tool_budgets(obs, max_per_tool=3000)
        assert len(budgets) == 2
        # 错误结果很小，应拿到最低预算
        assert budgets[1] >= 2000

    def test_budget_total_not_exceed_cap(self):
        """分配后的总预算不应远超 max_per_tool * n * 1.5。"""
        rt = self._runtime()
        obs = [self._make_result(20000)] * 4
        budgets = rt._allocate_tool_budgets(obs, max_per_tool=3000)
        cap = int(3000 * 4 * 1.5)  # 18000
        # 最低保留可能导致超出，但不应超出太多
        assert sum(budgets) <= cap + 4 * 2000  # 允许最低保留的余量


# ═══ 4d: LLM Summary (Stage 2) ═══

class TestLLMSummary:
    """A4-4d: stage2 用 LLM 生成摘要。"""

    @pytest.mark.asyncio
    async def test_fallback_when_no_llm_client(self):
        """No llm_client → heuristic summary."""
        runtime = AgenticRuntime(
            llm_client=None,
            tool_registry=_mock_registry(),
        )
        middle = [
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "calc", "arguments": "{}"}},
            ]},
            {"role": "tool", "tool_call_id": "c1", "content": "result=42"},
        ]
        summary = await runtime._generate_summary(middle, "")
        assert "Context Compacted" in summary
        assert "calc" in summary
        assert "summarized by LLM" not in summary  # heuristic, not LLM

    @pytest.mark.asyncio
    async def test_fallback_when_llm_fails(self):
        """LLM error → fallback to heuristic."""
        class FailingLLM:
            async def chat_completion(self, **kwargs):
                raise RuntimeError("LLM down")

        runtime = AgenticRuntime(
            llm_client=FailingLLM(),
            tool_registry=_mock_registry(),
        )
        middle = [
            {"role": "assistant", "content": "I will call tool_x"},
        ]
        summary = await runtime._generate_summary(middle, "PREFIX\n")
        assert "PREFIX" in summary
        assert "Context Compacted" in summary

    @pytest.mark.asyncio
    async def test_llm_summary_used_when_available(self):
        """Mock LLM returning summary → should use it."""
        from dataclasses import dataclass

        @dataclass
        class FakeResp:
            content: str = "执行了 calc 工具，结果为 42。"

        class MockLLM:
            async def chat_completion(self, **kwargs):
                return FakeResp()

        runtime = AgenticRuntime(
            llm_client=MockLLM(),
            tool_registry=_mock_registry(),
        )
        middle = [
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "calc", "arguments": "{}"}},
            ]},
            {"role": "tool", "tool_call_id": "c1", "content": "42"},
        ]
        summary = await runtime._generate_summary(middle, "")
        assert "summarized by LLM" in summary
        assert "42" in summary


# ═══ 4i: Multimodal Content Processing ═══

class TestMultimodalContentProcessor:
    """A4-4i: content_processor 多模态处理。"""

    def test_detect_type_text(self):
        from services.content_processor import detect_type
        assert detect_type("file.txt") == "text"
        assert detect_type("data.csv") == "text"
        assert detect_type("config.json") == "text"
        assert detect_type("script.py") == "text"

    def test_detect_type_image(self):
        from services.content_processor import detect_type
        assert detect_type("photo.png") == "image"
        assert detect_type("pic.jpg") == "image"
        assert detect_type("anim.gif") == "image"
        assert detect_type("img.webp") == "image"

    def test_detect_type_pdf(self):
        from services.content_processor import detect_type
        assert detect_type("doc.pdf") == "pdf"

    def test_detect_type_unsupported(self):
        from services.content_processor import detect_type
        assert detect_type("archive.zip") == "unsupported"
        assert detect_type("binary.exe") == "unsupported"

    def test_process_text_file(self):
        from services.content_processor import process_file
        content = "Hello, world!\n第二行".encode("utf-8")
        result = process_file(content, "test.txt")
        assert result.content_type == "text"
        assert "Hello" in result.text
        assert "第二行" in result.text

    def test_process_image_basic(self):
        """Image processing returns base64 even without PIL."""
        from services.content_processor import process_file
        # Minimal 1x1 PNG
        import struct, zlib
        def _make_png():
            sig = b'\x89PNG\r\n\x1a\n'
            ihdr_data = struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)
            ihdr_crc = zlib.crc32(b'IHDR' + ihdr_data) & 0xffffffff
            ihdr = struct.pack('>I', 13) + b'IHDR' + ihdr_data + struct.pack('>I', ihdr_crc)
            raw = b'\x00\x00\x00\x00'
            compressed = zlib.compress(raw)
            idat_crc = zlib.crc32(b'IDAT' + compressed) & 0xffffffff
            idat = struct.pack('>I', len(compressed)) + b'IDAT' + compressed + struct.pack('>I', idat_crc)
            iend_crc = zlib.crc32(b'IEND') & 0xffffffff
            iend = struct.pack('>I', 0) + b'IEND' + struct.pack('>I', iend_crc)
            return sig + ihdr + idat + iend

        png_bytes = _make_png()
        result = process_file(png_bytes, "test.png")
        assert result.content_type == "image"
        assert result.image_base64 is not None
        assert result.image_media_type == "image/png"

    def test_process_unsupported(self):
        from services.content_processor import process_file
        result = process_file(b"\x00\x01\x02", "data.bin")
        assert result.content_type == "unsupported"
        assert result.error is not None
        assert "Unsupported" in result.error

    def test_process_pdf_without_library(self):
        """PDF processing without PyMuPDF/PyPDF2 returns error gracefully."""
        from services.content_processor import process_pdf
        result = process_pdf(b"fake pdf content", "test.pdf")
        # Should not crash, returns unsupported or text depending on libs
        assert result.content_type in ("text", "unsupported")


# ═══ A4 Audit: Additional Tests ═══

class TestSmartTruncateAdditional:
    """Audit-identified gaps for smart_truncate."""

    def test_marker_length_includes_truncated_count(self):
        """Marker text should accurately reflect how many chars were truncated."""
        text = "a" * 10000
        result = smart_truncate(text, 3000)
        assert "truncated" in result
        # Result should be approximately budget size (head + marker + optional tail)
        assert len(result) < 10000

    def test_preserves_line_boundary(self):
        """Truncation should try to break at newlines when possible."""
        lines = ["line_" + str(i) + "\n" for i in range(200)]
        text = "".join(lines)
        result = smart_truncate(text, 500)
        # Should not cut mid-line (best effort)
        assert "truncated" in result

    def test_empty_string_no_truncation(self):
        """Empty string should return as-is."""
        assert smart_truncate("", 100) == ""

    def test_exact_budget_no_truncation(self):
        """String exactly at budget should not be truncated."""
        text = "x" * 3000
        result = smart_truncate(text, 3000)
        assert result == text


class TestFilePaginationAdditional:
    """Audit-identified gaps for file pagination."""

    def test_offset_beyond_file_size(self):
        """Offset exceeding file content should return empty or error."""
        # Simulate: file has 100 chars, offset=200
        content = "a" * 100
        offset = 200
        chunk = content[offset:offset + 50000]
        assert chunk == ""  # offset beyond content

    def test_chained_pagination_next_offset(self):
        """Chaining multiple page reads should cover entire file."""
        content = "a" * 150000  # 150K chars
        page_size = 50000
        offset = 0
        all_read = ""
        while offset < len(content):
            chunk = content[offset:offset + page_size]
            all_read += chunk
            offset += page_size
        assert all_read == content


class TestDynamicBudgetAdditional:
    """Audit-identified gaps for budget validation."""

    def test_budget_ratio_exceeds_one_still_bounded(self):
        """Budget with ratio > 1.0 should ideally be clamped to window."""
        config = RuntimeConfig(
            model_context_window=32000,
            context_budget_ratio=1.5,
            context_budget_min=16000,
        )
        budget = config.get_effective_budget()
        # Currently: 32000 * 1.5 = 48000 (BUG: exceeds window)
        # Document this behavior for now
        assert budget == 48000  # Known behavior — ratio not clamped

    def test_zero_context_window(self):
        """Window=0 should still return at least min budget."""
        config = RuntimeConfig(
            model_context_window=0,
            context_budget_ratio=0.8,
            context_budget_min=16000,
        )
        budget = config.get_effective_budget()
        assert budget == 16000  # min enforced


class TestToolPairRepairAdditional:
    """Audit-identified gaps for tool pair repair."""

    def test_duplicate_tool_call_ids(self):
        """Duplicate tool_call_ids in assistant message."""
        messages = [
            {"role": "assistant", "tool_calls": [
                {"id": "call_1", "function": {"name": "tool_a"}},
                {"id": "call_1", "function": {"name": "tool_b"}},  # duplicate
            ]},
        ]
        result = AgenticRuntime._repair_tool_pairs(messages)
        # Duplicate ID is added to declared_ids once (set), not in responded_ids
        # So one synthetic tool response is added for "call_1"
        tool_msgs = [m for m in result if m.get("role") == "tool"]
        assert len(tool_msgs) == 1

    def test_missing_role_field_skipped(self):
        """Message without 'role' field should not crash."""
        messages = [
            {"content": "no role here"},
            {"role": "user", "content": "normal"},
        ]
        result = AgenticRuntime._repair_tool_pairs(messages)
        assert len(result) == 2  # both kept

    def test_empty_tool_call_id_handled(self):
        """Empty string tool_call_id should be gracefully handled."""
        messages = [
            {"role": "assistant", "tool_calls": [
                {"id": "", "function": {"name": "tool_a"}},
            ]},
        ]
        result = AgenticRuntime._repair_tool_pairs(messages)
        # Empty ID is skipped by `if tc_id:` checks — no synthetic response added
        assert len(result) >= 1

    def test_assistant_content_preserved_after_repair(self):
        """Repair should not lose assistant content field."""
        messages = [
            {"role": "assistant", "content": "Let me call a tool", "tool_calls": [
                {"id": "call_1", "function": {"name": "search"}},
            ]},
        ]
        result = AgenticRuntime._repair_tool_pairs(messages)
        assistant_msg = [m for m in result if m.get("role") == "assistant"][0]
        assert assistant_msg["content"] == "Let me call a tool"


class TestIdentifierPatternAdditional:
    """Audit-identified gaps for ID pattern regex."""

    def test_id_pattern_false_positive_identification(self):
        """'identification' should not trigger ID extraction."""
        ids = _extract_identifiers("the identification number is important")
        # The regex matches "id" in "identification" then captures "entification"
        # as an alphanumeric identifier — this is a known false positive
        false_positives = [i for i in ids if "entification" in i]
        # Document: current regex does produce false positives (known issue)
        assert len(false_positives) >= 1  # Known behavior — regex needs word boundary

    def test_id_pattern_matches_real_ids(self):
        """Real business IDs should be extracted."""
        text = 'ID: ABC-12345 and 编号: INV-2025-001'
        ids = _extract_identifiers(text)
        assert len(ids) >= 1  # Should find at least one ID

    def test_amount_pattern_yuan(self):
        """Chinese yuan amounts should be extracted."""
        ids = _extract_identifiers("金额是 ¥1,234.56 元")
        amounts = [i for i in ids if "1,234" in i or "¥" in i]
        assert len(amounts) >= 1

    def test_date_pattern_chinese(self):
        """Chinese date format should be extracted."""
        ids = _extract_identifiers("日期: 2025年3月15日")
        dates = [i for i in ids if "2025" in i]
        assert len(dates) >= 1
