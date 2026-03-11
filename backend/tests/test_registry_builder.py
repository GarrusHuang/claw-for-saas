"""Tests for tools/registry_builder.py — tool set assembly (A2+A3)."""
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.registry_builder import (
    build_shared_registry,
    build_capability_registry,
    build_plan_registry,
    build_full_registry,
    build_auto_registry,
    build_execute_registry,
)


class TestBuildSharedRegistry:
    def test_contains_calculator_tools(self):
        reg = build_shared_registry()
        names = reg.get_tool_names()
        for tool in ["arithmetic", "numeric_compare", "sum_values", "calculate_ratio", "date_diff"]:
            assert tool in names, f"Missing calculator tool: {tool}"

    def test_contains_skill_reference(self):
        reg = build_shared_registry()
        assert "read_reference" in reg.get_tool_names()

    def test_all_read_only(self):
        reg = build_shared_registry()
        for name in reg.get_tool_names():
            assert reg.is_read_only(name) is True, f"{name} should be read_only"

    def test_tool_count(self):
        reg = build_shared_registry()
        assert len(reg.get_tool_names()) == 6  # 5 calculator + 1 skill_reference


class TestBuildCapabilityRegistry:
    def test_contains_subagent_tools(self):
        reg = build_capability_registry()
        names = reg.get_tool_names()
        assert "spawn_subagent" in names
        assert "spawn_subagents" in names

    def test_no_parallel_review(self):
        """A3: parallel_review removed."""
        reg = build_capability_registry()
        assert "parallel_review" not in reg.get_tool_names()

    def test_contains_memory_tools(self):
        reg = build_capability_registry()
        names = reg.get_tool_names()
        assert "save_memory" in names
        assert "recall_memory" in names

    def test_contains_file_tools(self):
        reg = build_capability_registry()
        names = reg.get_tool_names()
        assert "read_uploaded_file" in names
        assert "list_user_files" in names

    def test_contains_code_tools(self):
        reg = build_capability_registry()
        names = reg.get_tool_names()
        assert "read_source_file" in names
        assert "write_source_file" in names
        assert "run_command" in names

    def test_contains_skill_management(self):
        reg = build_capability_registry()
        names = reg.get_tool_names()
        assert "create_skill" in names
        assert "update_skill" in names


class TestBuildPlanRegistry:
    def test_contains_propose_plan(self):
        reg = build_plan_registry()
        assert "propose_plan" in reg.get_tool_names()

    def test_only_one_tool(self):
        reg = build_plan_registry()
        assert len(reg.get_tool_names()) == 1


class TestBuildFullRegistry:
    def test_contains_all_tools(self):
        reg = build_full_registry()
        names = reg.get_tool_names()
        # Shared
        assert "arithmetic" in names
        assert "read_reference" in names
        # Capability
        assert "spawn_subagent" in names
        assert "save_memory" in names
        # Plan
        assert "propose_plan" in names

    def test_no_duplicates(self):
        reg = build_full_registry()
        names = reg.get_tool_names()
        assert len(names) == len(set(names))


class TestBackwardsCompat:
    def test_auto_is_full(self):
        """A2: build_auto_registry is alias for build_full_registry."""
        auto = build_auto_registry()
        full = build_full_registry()
        assert set(auto.get_tool_names()) == set(full.get_tool_names())

    def test_execute_is_full(self):
        """A2: build_execute_registry is alias for build_full_registry."""
        execute = build_execute_registry()
        full = build_full_registry()
        assert set(execute.get_tool_names()) == set(full.get_tool_names())
