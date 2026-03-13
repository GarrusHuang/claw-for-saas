"""
Skill 参考资料查询工具。

允许 Agent 在 ReAct 循环中按需查询 Skill 的详细参考资料（L3 加载）。
Phase 2 集成 SkillLoader 后会替换为真实实现。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.tool_registry import ToolRegistry

skill_reference_registry = ToolRegistry()


@skill_reference_registry.tool(
    description="Query detailed reference materials from a Skill. "
                "Use when the knowledge in the system prompt is insufficient. "
                "For example, look up specific expense standard tables or contract clause templates.",
    read_only=True,
)
async def read_reference(skill_name: str, reference_name: str) -> dict:
    """Read reference material from a Skill's references directory."""
    try:
        from skills.loader import SkillLoader
        loader = SkillLoader()
        content = loader.read_reference(skill_name, reference_name)
        if content and not content.startswith("[ERROR]"):
            return {
                "skill_name": skill_name,
                "reference_name": reference_name,
                "content": content,
                "loaded": True,
            }
    except Exception:
        pass
    return {
        "skill_name": skill_name,
        "reference_name": reference_name,
        "content": f"Reference '{reference_name}' not found in skill '{skill_name}'.",
        "loaded": False,
    }
