"""Tests for agent/prompt.py — 8-layer modular prompt builder (A2 simplified)."""
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.prompt import (
    PromptLayer,
    PromptBuilder,
    PromptContext,
    PromptSection,
    ToolSummary,
    PROMPT_MODE_LAYERS,
)
from agent.plan_tracker import PlanTracker
from core.context import current_plan_tracker


# ── PromptLayer ──


class TestPromptLayer:
    def test_ordering(self):
        assert PromptLayer.IDENTITY < PromptLayer.SOUL < PromptLayer.SAFETY
        assert PromptLayer.EXTRA == 7

    def test_all_layers(self):
        assert len(PromptLayer) == 8


# ── PromptBuilder init ──


class TestPromptBuilderInit:
    def test_default_sections_registered(self):
        pb = PromptBuilder()
        sections = pb._sections
        assert "identity" in sections
        assert "soul" in sections
        assert "safety" in sections
        assert "tools" in sections
        assert "skills" in sections
        assert "memory" in sections
        assert "runtime" in sections
        assert "plan_guidance" in sections
        assert "knowledge" in sections
        assert len(sections) == 9


# ── register / unregister ──


class TestSectionRegistration:
    def test_register_new(self):
        pb = PromptBuilder()
        custom = PromptSection(
            layer=PromptLayer.EXTRA, priority=99,
            name="custom", builder_fn=lambda ctx: "custom output",
        )
        pb.register_section(custom)
        assert "custom" in pb._sections

    def test_replace_existing(self):
        pb = PromptBuilder()
        replacement = PromptSection(
            layer=PromptLayer.IDENTITY, priority=0,
            name="identity", builder_fn=lambda ctx: "New Identity",
        )
        pb.register_section(replacement)
        prompt = pb.build_system_prompt(mode="none")  # Only IDENTITY layer
        assert "New Identity" in prompt

    def test_unregister_existing(self):
        pb = PromptBuilder()
        assert pb.unregister_section("skills") is True
        assert "skills" not in pb._sections

    def test_unregister_nonexistent(self):
        pb = PromptBuilder()
        assert pb.unregister_section("nonexistent") is False


# ── build_system_prompt ──


class TestBuildSystemPrompt:
    def test_mode_none_identity_only(self):
        pb = PromptBuilder()
        prompt = pb.build_system_prompt(mode="none")
        assert "Claw AI Agent Runtime" in prompt
        assert "<safety>" not in prompt

    def test_mode_full_includes_all(self):
        pb = PromptBuilder()
        prompt = pb.build_system_prompt(
            mode="full",
            skill_knowledge="Test skill",
            memory_context="User prefers Chinese",
            user_id="U1",
            session_id="S1",
        )
        assert "Claw AI Agent Runtime" in prompt
        assert "<safety>" in prompt
        assert "<skills>" in prompt
        assert "Test skill" in prompt
        assert "<memory>" in prompt
        assert "User prefers Chinese" in prompt
        assert "<user_id>U1</user_id>" in prompt

    def test_mode_minimal_excludes_skills_memory(self):
        pb = PromptBuilder()
        prompt = pb.build_system_prompt(
            mode="minimal",
            skill_knowledge="should not appear",
            memory_context="should not appear",
        )
        assert "should not appear" not in prompt
        assert "<safety>" in prompt  # safety is in minimal

    def test_empty_skills_no_skill_content(self):
        pb = PromptBuilder()
        prompt = pb.build_system_prompt(skill_knowledge="")
        assert "\n<skills>\n\n</skills>" not in prompt

    def test_empty_memory_no_memory_content(self):
        pb = PromptBuilder()
        prompt = pb.build_system_prompt(memory_context="")
        assert "\n<memory>\n\n</memory>" not in prompt


# ── Tools section ──


class TestToolsSection:
    def test_no_tools_empty(self):
        pb = PromptBuilder()
        prompt = pb.build_system_prompt(tool_summaries=[])
        assert "<tools>" not in prompt

    def test_tools_categorized(self):
        tools = [
            ToolSummary(name="read_file", description="Read a file", read_only=True),
            ToolSummary(name="write_file", description="Write a file", read_only=False),
        ]
        pb = PromptBuilder()
        prompt = pb.build_system_prompt(tool_summaries=tools)
        assert "查询工具" in prompt
        assert "能力工具" in prompt
        assert "read_file" in prompt
        assert "write_file" in prompt


# ── Plan guidance (A2 simplified — no AUTO/EXECUTE distinction) ──


class TestPlanGuidance:
    def test_plan_guidance_present(self):
        pb = PromptBuilder()
        prompt = pb.build_system_prompt()
        assert "<plan_guidance>" in prompt
        assert "propose_plan" in prompt

    def test_plan_guidance_mentions_progress(self):
        pb = PromptBuilder()
        prompt = pb.build_system_prompt()
        assert "进度" in prompt


# ── build_user_message ──


class TestBuildUserMessage:
    def test_message_only(self):
        pb = PromptBuilder()
        msg = pb.build_user_message(message="hello")
        assert msg == "hello"

    def test_with_materials(self):
        pb = PromptBuilder()
        msg = pb.build_user_message(message="请分析", materials_summary="发票.pdf: 金额1000")
        assert "<materials>" in msg
        assert "发票.pdf" in msg
        assert "请分析" in msg


# ── Section error handling ──


class TestSectionErrorHandling:
    def test_failing_section_skipped(self):
        pb = PromptBuilder()
        bad_section = PromptSection(
            layer=PromptLayer.EXTRA, priority=99,
            name="bad", builder_fn=lambda ctx: 1/0,
        )
        pb.register_section(bad_section)
        # Should not raise, just skip the bad section
        prompt = pb.build_system_prompt(mode="none")
        assert "Claw AI Agent Runtime" in prompt


# ── PROMPT_MODE_LAYERS ──


class TestPromptModeLayers:
    def test_full_has_all_layers(self):
        assert PROMPT_MODE_LAYERS["full"] == set(PromptLayer)

    def test_none_has_only_identity(self):
        assert PROMPT_MODE_LAYERS["none"] == {PromptLayer.IDENTITY}

    def test_minimal_has_expected_layers(self):
        minimal = PROMPT_MODE_LAYERS["minimal"]
        assert PromptLayer.IDENTITY in minimal
        assert PromptLayer.SOUL in minimal
        assert PromptLayer.SAFETY in minimal
        assert PromptLayer.TOOLS in minimal
        assert PromptLayer.EXTRA in minimal
        assert PromptLayer.SKILLS not in minimal
        assert PromptLayer.MEMORY not in minimal


# ── Plan state injection into prompt ──


class TestPlanStateInjection:
    """plan_guidance 从 ContextVar 读取已恢复的 PlanTracker 并注入状态。"""

    def _build_with_tracker(self, tracker: PlanTracker | None) -> str:
        token = current_plan_tracker.set(tracker)
        try:
            pb = PromptBuilder()
            return pb.build_system_prompt()
        finally:
            current_plan_tracker.reset(token)

    def test_no_tracker_no_injection(self):
        """无 PlanTracker 时，plan_guidance 不含步骤状态。"""
        prompt = self._build_with_tracker(None)
        assert "<plan_guidance>" in prompt
        assert "当前存在未完成的执行计划" not in prompt

    def test_all_completed_no_injection(self):
        """所有步骤已完成时，不注入续接指令。"""
        saved = [
            {"action": "查询数据", "status": "completed"},
            {"action": "生成报告", "status": "completed"},
        ]
        tracker = PlanTracker.restore(saved)
        prompt = self._build_with_tracker(tracker)
        assert "当前存在未完成的执行计划" not in prompt

    def test_pending_steps_inject_state(self):
        """有 pending 步骤时，注入完整状态 + 续接指令。"""
        saved = [
            {"action": "查询数据", "status": "completed"},
            {"action": "分析结果", "status": "pending"},
            {"action": "生成报告", "status": "pending"},
        ]
        tracker = PlanTracker.restore(saved)
        prompt = self._build_with_tracker(tracker)
        assert "当前存在未完成的执行计划" in prompt
        assert "update_plan_step" in prompt
        assert "✅ 步骤 0: 查询数据 [completed]" in prompt
        assert "⬚ 步骤 1: 分析结果 [pending]" in prompt
        assert "⬚ 步骤 2: 生成报告 [pending]" in prompt
        assert "从步骤 1 开始" in prompt
        assert "status='running'" in prompt

    def test_running_step_interrupted(self):
        """有 running 步骤（被中断）时，提示继续完成。"""
        saved = [
            {"action": "查询数据", "status": "completed"},
            {"action": "分析结果", "status": "running"},
            {"action": "生成报告", "status": "pending"},
        ]
        tracker = PlanTracker.restore(saved)
        prompt = self._build_with_tracker(tracker)
        assert "当前存在未完成的执行计划" in prompt
        assert "🔄 步骤 1: 分析结果 [running]" in prompt
        assert "步骤 1 上次被中断" in prompt
        assert "status='completed'" in prompt

    def test_failed_step_shows_icon(self):
        """failed 步骤显示 ❌ 图标。"""
        saved = [
            {"action": "查询数据", "status": "failed"},
            {"action": "分析结果", "status": "pending"},
        ]
        tracker = PlanTracker.restore(saved)
        prompt = self._build_with_tracker(tracker)
        assert "❌ 步骤 0: 查询数据 [failed]" in prompt
        assert "从步骤 1 开始" in prompt

    def test_empty_steps_no_injection(self):
        """空步骤列表不注入。"""
        tracker = PlanTracker.restore([])
        prompt = self._build_with_tracker(tracker)
        assert "当前存在未完成的执行计划" not in prompt
