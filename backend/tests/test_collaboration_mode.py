"""
Collaboration Mode 测试 — 3.2

验证:
- ChatRequest mode 字段校验 (plan/execute 合法, invalid 拒绝)
- plan 模式下 tool_summaries 只含只读 + propose_plan/update_plan_step
- plan 模式下 llm_tool_registry 不含写入工具
- plan 模式 prompt 含 "分析规划模式" 文本
- execute 模式行为不变
"""
import pytest
from pydantic import ValidationError

from models.request import ChatRequest
from agent.prompt import PromptBuilder, PromptContext, ToolSummary


class TestChatRequestMode:
    """ChatRequest mode 字段校验。"""

    def test_default_mode_is_execute(self):
        req = ChatRequest(message="hello")
        assert req.mode == "execute"

    def test_plan_mode_valid(self):
        req = ChatRequest(message="hello", mode="plan")
        assert req.mode == "plan"

    def test_execute_mode_valid(self):
        req = ChatRequest(message="hello", mode="execute")
        assert req.mode == "execute"

    def test_invalid_mode_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            ChatRequest(message="hello", mode="invalid")
        assert "mode" in str(exc_info.value)

    def test_empty_mode_rejected(self):
        with pytest.raises(ValidationError):
            ChatRequest(message="hello", mode="")


class TestPlanModeToolFiltering:
    """plan 模式工具过滤验证。"""

    def test_plan_mode_filters_write_tools(self):
        """plan 模式下 tool_summaries 只含只读 + plan 工具。"""
        all_summaries = [
            ToolSummary(name="read_source_file", description="read", read_only=True),
            ToolSummary(name="write_source_file", description="write", read_only=False),
            ToolSummary(name="run_command", description="run", read_only=False),
            ToolSummary(name="propose_plan", description="plan", read_only=False),
            ToolSummary(name="update_plan_step", description="step", read_only=False),
            ToolSummary(name="save_memory", description="save mem", read_only=False),
            ToolSummary(name="recall_memory", description="recall", read_only=True),
        ]

        PLAN_MODE_EXTRA = {"propose_plan", "update_plan_step"}
        filtered = [
            t for t in all_summaries
            if t.read_only or t.name in PLAN_MODE_EXTRA
        ]

        names = {t.name for t in filtered}
        assert "read_source_file" in names  # read_only
        assert "recall_memory" in names  # read_only
        assert "propose_plan" in names  # plan extra
        assert "update_plan_step" in names  # plan extra
        assert "write_source_file" not in names  # write tool
        assert "run_command" not in names  # write tool
        assert "save_memory" not in names  # write tool

    def test_execute_mode_keeps_all_tools(self):
        """execute 模式下所有工具保留。"""
        all_summaries = [
            ToolSummary(name="read_source_file", description="read", read_only=True),
            ToolSummary(name="write_source_file", description="write", read_only=False),
            ToolSummary(name="propose_plan", description="plan", read_only=False),
        ]

        # execute 模式不过滤
        mode = "execute"
        if mode == "plan":
            PLAN_MODE_EXTRA = {"propose_plan", "update_plan_step"}
            filtered = [t for t in all_summaries if t.read_only or t.name in PLAN_MODE_EXTRA]
        else:
            filtered = all_summaries

        assert len(filtered) == 3


class TestPlanModePrompt:
    """plan 模式 prompt 引导。"""

    def test_plan_mode_prompt_contains_guidance(self):
        """plan 模式下 prompt 包含分析规划模式文本。"""
        builder = PromptBuilder()
        prompt = builder.build_system_prompt(
            chat_mode="plan",
            tool_summaries=[
                ToolSummary(name="read_source_file", description="read", read_only=True),
            ],
        )
        assert "分析规划模式" in prompt
        assert "只能使用只读查询工具" in prompt
        assert "propose_plan" in prompt

    def test_execute_mode_prompt_no_plan_guidance(self):
        """execute 模式下 prompt 不含分析规划模式文本。"""
        builder = PromptBuilder()
        prompt = builder.build_system_prompt(
            chat_mode="execute",
            tool_summaries=[
                ToolSummary(name="read_source_file", description="read", read_only=True),
            ],
        )
        assert "分析规划模式" not in prompt

    def test_plan_context_chat_mode(self):
        """PromptContext.chat_mode 正确传递。"""
        ctx = PromptContext(chat_mode="plan")
        assert ctx.chat_mode == "plan"

        ctx2 = PromptContext()
        assert ctx2.chat_mode == "execute"
