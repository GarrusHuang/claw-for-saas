"""
MCP 标准工具接口 — 6 个工具通过 ContextVar 获取 MCPProvider。

SaaS 宿主实现 MCPProvider Protocol，通过 Gateway 注入。
Agent 通过这些工具拉取业务数据（表单 schema、规则、候选值等）。

模式参考: memory_tools.py (ContextVar 注入 + error dict fallback)
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from core.context import current_mcp_provider
from core.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)

mcp_registry = ToolRegistry()


# ─── MCPProvider Protocol ───

@runtime_checkable
class MCPProvider(Protocol):
    """MCP 数据提供者协议 — SaaS 宿主实现此接口。"""

    async def get_form_schema(self, form_type: str) -> dict: ...
    async def get_business_rules(self, rule_type: str) -> dict: ...
    async def get_candidate_types(self, category: str) -> dict: ...
    async def get_protected_values(self, context: str) -> dict: ...
    async def submit_form_data(self, form_type: str, data: dict) -> dict: ...
    async def query_data(self, query_type: str, params: dict) -> dict: ...


# ─── Helper ───

def _get_provider() -> MCPProvider:
    """从 ContextVar 获取 MCPProvider，fallback 到 DefaultMCPProvider。"""
    provider = current_mcp_provider.get(None)
    if provider is not None:
        return provider
    from tools.mcp.defaults import DefaultMCPProvider
    return DefaultMCPProvider()


# ─── 6 个 MCP 工具 ───

@mcp_registry.tool(
    description=(
        "获取表单 schema 定义。"
        "返回表单的字段列表、类型约束、验证规则等元数据。"
        "用于了解需要填写哪些字段及其格式要求。"
    ),
    read_only=True,
)
async def get_form_schema(form_type: str) -> dict:
    """获取指定类型表单的 schema。"""
    provider = _get_provider()
    return await provider.get_form_schema(form_type)


@mcp_registry.tool(
    description=(
        "获取业务规则。"
        "返回审批规则、计算规则、合规约束等业务逻辑。"
        "用于理解业务处理的约束条件。"
    ),
    read_only=True,
)
async def get_business_rules(rule_type: str) -> dict:
    """获取指定类型的业务规则。"""
    provider = _get_provider()
    return await provider.get_business_rules(rule_type)


@mcp_registry.tool(
    description=(
        "获取候选值类型列表。"
        "返回下拉选项、枚举类型、分类树等可选值。"
        "用于填充表单选项或进行分类。"
    ),
    read_only=True,
)
async def get_candidate_types(category: str) -> dict:
    """获取指定分类的候选值列表。"""
    provider = _get_provider()
    return await provider.get_candidate_types(category)


@mcp_registry.tool(
    description=(
        "获取受保护的值。"
        "返回不可修改的预设值或系统计算值。"
        "Agent 不应覆盖这些值。"
    ),
    read_only=True,
)
async def get_protected_values(context: str) -> dict:
    """获取指定上下文的受保护值。"""
    provider = _get_provider()
    return await provider.get_protected_values(context)


@mcp_registry.tool(
    description=(
        "提交表单数据到宿主系统。"
        "将填写完成的表单数据发送给 SaaS 宿主处理。"
        "返回提交结果（成功/失败/需要补充信息）。"
    ),
    read_only=False,
)
async def submit_form_data(form_type: str, data: dict) -> dict:
    """提交表单数据。"""
    provider = _get_provider()
    return await provider.submit_form_data(form_type, data)


@mcp_registry.tool(
    description=(
        "查询业务数据。"
        "从宿主系统查询历史记录、统计数据、关联信息等。"
        "支持多种查询类型和参数组合。"
    ),
    read_only=True,
)
async def query_data(query_type: str, params: dict) -> dict:
    """查询业务数据。"""
    provider = _get_provider()
    return await provider.query_data(query_type, params)
