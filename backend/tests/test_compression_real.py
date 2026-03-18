"""
T2: 真实大小对话压缩测试。

验证 20+ 消息在各阶段压缩后仍在预算内。
"""
from __future__ import annotations

import json
import pytest

from core.runtime import AgenticRuntime, RuntimeConfig
from core.tool_registry import ToolRegistry
from core.tool_protocol import ToolCallParser
from core.token_estimator import estimate_messages_tokens


def _build_large_conversation(msg_count: int = 25) -> list[dict]:
    """构建大型对话消息列表 (user/assistant/tool 混合)。"""
    messages = [{"role": "system", "content": "你是一个测试助手。" * 50}]

    for i in range(msg_count):
        messages.append({
            "role": "user",
            "content": f"请帮我处理第 {i+1} 个任务。这是一段较长的用户消息内容，用于模拟真实场景。" * 5,
        })
        # assistant with tool call
        tc_id = f"call_{i:04d}"
        messages.append({
            "role": "assistant",
            "content": f"我来执行第 {i+1} 步操作。",
            "tool_calls": [{
                "id": tc_id,
                "type": "function",
                "function": {
                    "name": "read_uploaded_file",
                    "arguments": json.dumps({"file_id": f"f{i}"}),
                },
            }],
        })
        # tool result
        messages.append({
            "role": "tool",
            "tool_call_id": tc_id,
            "content": json.dumps({
                "filename": f"file_{i}.txt",
                "content": f"这是文件 {i} 的内容。" * 100,
                "size_bytes": 5000,
            }),
        })

    return messages


class TestCompressionStages:
    """测试各阶段压缩效果。"""

    def test_stage1_truncates_old_tool_results(self):
        """Stage 1 应截断旧的工具结果，保留最近 4 条。"""
        config = RuntimeConfig(
            max_iterations=5,
            context_budget_tokens=0,
            model_context_window=8000,
            compress_threshold_ratio=0.70,
        )
        runtime = AgenticRuntime(
            llm_client=None,
            tool_registry=ToolRegistry(),
            tool_parser=ToolCallParser(),
            config=config,
        )

        messages = _build_large_conversation(10)
        result = runtime._stage1_truncate_tool_results(messages)

        # 应该有消息被截断
        total_len_before = sum(len(str(m.get("content", ""))) for m in messages)
        total_len_after = sum(len(str(m.get("content", ""))) for m in result)
        assert total_len_after < total_len_before

    def test_stage3_metadata_mode(self):
        """Stage 3 应大幅压缩到 system + 最近 4 条 + 摘要。"""
        config = RuntimeConfig(max_iterations=5)
        runtime = AgenticRuntime(
            llm_client=None,
            tool_registry=ToolRegistry(),
            tool_parser=ToolCallParser(),
            config=config,
        )

        messages = _build_large_conversation(10)
        result = runtime._stage3_metadata_mode(messages)

        # system(1) + summary(1) + tail(4) = 6
        assert len(result) <= 6
        assert result[0]["role"] == "system"
        assert "compacted" in result[1]["content"].lower()

    def test_stage4_drops_oldest(self):
        """Stage 4 应逐条删最旧消息直到 fit。"""
        config = RuntimeConfig(
            max_iterations=5,
            context_budget_tokens=0,
            model_context_window=4000,
        )
        runtime = AgenticRuntime(
            llm_client=None,
            tool_registry=ToolRegistry(),
            tool_parser=ToolCallParser(),
            config=config,
        )

        messages = _build_large_conversation(15)
        budget = config.get_effective_budget()
        result = runtime._stage4_drop_oldest(messages, budget, tools_schema=None)

        estimated = estimate_messages_tokens(result)
        assert estimated <= budget
        # system 消息保留
        assert result[0]["role"] == "system"

    @pytest.mark.asyncio
    async def test_full_compact_fits_budget(self):
        """完整 compact 流程后应在预算内。"""
        config = RuntimeConfig(
            max_iterations=5,
            context_budget_tokens=0,
            model_context_window=6000,
            compress_threshold_ratio=0.70,
        )
        runtime = AgenticRuntime(
            llm_client=None,
            tool_registry=ToolRegistry(),
            tool_parser=ToolCallParser(),
            config=config,
        )

        messages = _build_large_conversation(20)
        budget = config.get_effective_budget()

        # 确认压缩前超预算
        before = estimate_messages_tokens(messages)
        assert before > budget

        result = await runtime._compact_messages(messages)
        after = estimate_messages_tokens(result)

        # 压缩后应在预算内
        assert after <= budget
        # 至少保留 system 消息
        assert any(m.get("role") == "system" for m in result)

    def test_repair_tool_pairs(self):
        """压缩后工具对应完整。"""
        config = RuntimeConfig(max_iterations=5)
        runtime = AgenticRuntime(
            llm_client=None,
            tool_registry=ToolRegistry(),
            tool_parser=ToolCallParser(),
            config=config,
        )

        # 构造孤立 tool 消息
        messages = [
            {"role": "system", "content": "test"},
            {"role": "tool", "tool_call_id": "orphan_1", "content": "orphan result"},
            {"role": "assistant", "content": "ok", "tool_calls": [
                {"id": "tc_1", "type": "function", "function": {"name": "test", "arguments": "{}"}}
            ]},
        ]
        result = AgenticRuntime._repair_tool_pairs(messages)

        # 孤立 tool 应被删除
        orphan_tools = [m for m in result if m.get("tool_call_id") == "orphan_1"]
        assert len(orphan_tools) == 0

        # 孤立 assistant tool_call 应被补充 tool 响应
        tool_responses = [m for m in result if m.get("tool_call_id") == "tc_1"]
        assert len(tool_responses) == 1
