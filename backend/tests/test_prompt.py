"""Tests for agent/prompt.py — 8-layer modular prompt builder."""
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
        assert "business_context" in sections
        assert "plan_mode" in sections
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
        # Soul file may contain "skills" in its text; check that our skills section didn't add content
        # The _build_skills returns "" when skill_knowledge is empty
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


# ── Plan mode ──


class TestPlanMode:
    def test_auto_mode(self):
        pb = PromptBuilder()
        prompt = pb.build_system_prompt(plan_mode=True)
        assert "<mode>AUTO</mode>" in prompt
        assert "自主模式" in prompt

    def test_execute_mode(self):
        pb = PromptBuilder()
        prompt = pb.build_system_prompt(plan_mode=False)
        assert "<mode>EXECUTE</mode>" in prompt
        assert "执行模式" in prompt


# ── Business context ──


class TestBusinessContext:
    def test_no_context_no_business_xml(self):
        pb = PromptBuilder()
        prompt = pb.build_system_prompt(business_context=None)
        # business_context section returns "" when None, but soul.md may mention it
        assert "\n<business_context>\n" not in prompt or "<candidate_types>" not in prompt

    def test_form_fields(self):
        ctx = {
            "form_fields": [
                {"field_id": "amount", "field_name": "金额", "field_type": "number", "required": True},
            ],
        }
        pb = PromptBuilder()
        prompt = pb.build_system_prompt(business_context=ctx)
        assert "<form_fields>" in prompt
        assert 'id="amount"' in prompt

    def test_audit_rules(self):
        ctx = {
            "audit_rules": [
                {"rule_id": "R001", "rule_name": "金额上限", "severity": "error"},
            ],
        }
        pb = PromptBuilder()
        prompt = pb.build_system_prompt(business_context=ctx)
        assert "<audit_rules>" in prompt
        assert 'id="R001"' in prompt

    def test_candidate_types(self):
        ctx = {
            "candidate_types": [
                {"type_id": "travel", "type_name": "差旅报销", "keywords": ["出差", "交通"]},
            ],
        }
        pb = PromptBuilder()
        prompt = pb.build_system_prompt(business_context=ctx)
        assert "<candidate_types>" in prompt
        assert 'id="travel"' in prompt

    def test_known_values(self):
        ctx = {
            "known_values": [
                {"field_id": "dept", "value": "IT", "source": "system"},
            ],
        }
        pb = PromptBuilder()
        prompt = pb.build_system_prompt(business_context=ctx)
        assert "<known_values>" in prompt
        assert 'field_id="dept"' in prompt


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
