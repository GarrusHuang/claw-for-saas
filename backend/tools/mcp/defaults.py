"""
DefaultMCPProvider — MCP 未配置时的 fallback。

所有方法返回 error + hint，引导 SaaS 集成方实现 MCPProvider。
"""

from __future__ import annotations


class DefaultMCPProvider:
    """MCP 未配置时的默认实现 — 所有方法返回错误提示。"""

    async def get_form_schema(self, form_type: str) -> dict:
        return {
            "error": "MCP not configured",
            "hint": "SaaS host should implement MCPProvider.get_form_schema()",
        }

    async def get_business_rules(self, rule_type: str) -> dict:
        return {
            "error": "MCP not configured",
            "hint": "SaaS host should implement MCPProvider.get_business_rules()",
        }

    async def get_candidate_types(self, category: str) -> dict:
        return {
            "error": "MCP not configured",
            "hint": "SaaS host should implement MCPProvider.get_candidate_types()",
        }

    async def get_protected_values(self, context: str) -> dict:
        return {
            "error": "MCP not configured",
            "hint": "SaaS host should implement MCPProvider.get_protected_values()",
        }

    async def submit_form_data(self, form_type: str, data: dict) -> dict:
        return {
            "error": "MCP not configured",
            "hint": "SaaS host should implement MCPProvider.submit_form_data()",
        }

    async def query_data(self, query_type: str, params: dict) -> dict:
        return {
            "error": "MCP not configured",
            "hint": "SaaS host should implement MCPProvider.query_data()",
        }
