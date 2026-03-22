"""
Tool registry builder — assembles built-in tool sets.

A2 简化: 去掉 AUTO/EXECUTE 双模式，统一为单一 registry。
propose_plan 始终可用，作为纯进度展示工具。

Built-in tools (no domain-specific tools):
- calculator: numeric_compare, sum_values, calculate_ratio, date_diff, arithmetic
- skill_reference: read_reference
- plan: propose_plan
- subagent: spawn_subagent, spawn_subagents
- file: read_uploaded_file, list_user_files, analyze_file
- browser: open_url, page_screenshot, page_extract_text
- code: read_source_file, write_source_file, apply_patch, run_command
- memory: save_memory, recall_memory
- skill: create_skill, update_skill
- mcp: get_form_schema, get_business_rules, get_candidate_types,
       get_protected_values, submit_form_data, query_data
- schedule: create_schedule, list_schedules, delete_schedule
- interaction: request_user_input
"""
from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.tool_registry import ToolRegistry


def build_shared_registry() -> ToolRegistry:
    """
    Build shared tools registry (read-only tools).

    - calculator: 5 tools
    - skill_reference: 1 tool
    """
    from tools.builtin.calculator import calculator_registry
    from tools.builtin.skill_reference import skill_reference_registry

    merged = calculator_registry.merge(skill_reference_registry)
    return merged


def build_capability_registry() -> ToolRegistry:
    """
    Build capability tools registry (all built-in capability tools, no plan).

    - skill: create_skill, update_skill
    - subagent: spawn_subagent, spawn_subagents
    - file: read_uploaded_file, list_user_files, analyze_file
    - browser: open_url, page_screenshot, page_extract_text
    - code: read_source_file, write_source_file, apply_patch, run_command
    - memory: save_memory, recall_memory
    """
    from tools.builtin.skill_tools import skill_capability_registry
    from tools.builtin.subagent_tools import subagent_capability_registry
    from tools.builtin.file_tools import file_capability_registry
    from tools.builtin.browser_tools import browser_capability_registry
    from tools.builtin.code_tools import code_capability_registry
    from tools.builtin.apply_patch import apply_patch_registry
    from tools.builtin.memory_tools import memory_capability_registry
    from tools.builtin.schedule_tools import schedule_capability_registry
    from tools.builtin.interaction import interaction_capability_registry

    merged = skill_capability_registry.merge(subagent_capability_registry)
    merged = merged.merge(file_capability_registry)
    merged = merged.merge(browser_capability_registry)
    merged = merged.merge(code_capability_registry)
    merged = merged.merge(apply_patch_registry)
    merged = merged.merge(memory_capability_registry)
    merged = merged.merge(schedule_capability_registry)
    merged = merged.merge(interaction_capability_registry)
    return merged


def build_plan_registry() -> ToolRegistry:
    """Build plan tool registry (1 tool: propose_plan)."""
    from tools.builtin.plan_tools import plan_capability_registry
    return plan_capability_registry


def build_mcp_registry() -> ToolRegistry:
    """Build MCP standard tool registry (6 tools)."""
    from tools.mcp.mcp_tools import mcp_registry
    return mcp_registry


def build_full_registry(mcp_enabled: bool = False) -> ToolRegistry:
    """
    Build full tool registry (shared + capability + plan + conditionally mcp).
    Single unified registry — no more AUTO/EXECUTE split.

    Args:
        mcp_enabled: Only register MCP tools when True (avoids exposing
                     6 stub tools that return default/fallback data).
    """
    shared = build_shared_registry()
    capability = build_capability_registry()
    plan = build_plan_registry()
    merged = shared.merge(capability).merge(plan)
    if mcp_enabled:
        mcp = build_mcp_registry()
        merged = merged.merge(mcp)
    return merged
