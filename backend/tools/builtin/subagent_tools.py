"""
子智能体工具。

主 Agent 通过 spawn_subagent 工具调用子智能体。
子智能体有独立的 AgenticRuntime 实例和独立上下文。

实际执行由 SubagentRunner 完成（通过 contextvars 注入）。

Phase 16 增强:
- agent_role: 指定专业角色 (如 "data-validator", "compliance-reviewer")
- inherit_context: 是否继承主 Agent 的业务上下文
"""

from __future__ import annotations

import contextvars
from typing import Any

from core.tool_registry import ToolRegistry

subagent_capability_registry = ToolRegistry()

# SubagentRunner 注入 (由 Gateway 设置)
_subagent_runner: contextvars.ContextVar[Any] = contextvars.ContextVar(
    "_subagent_runner", default=None
)


@subagent_capability_registry.tool(
    description=(
        "派遣子智能体执行子任务。子智能体有独立上下文，完成后返回结果。"
        "适用场景: "
        "1) 需要大量 MCP 查询的数据收集 (subagent_type='query')  "
        "2) 需要执行具体子任务 (subagent_type='task')  "
        "3) 需要专业角色审查 (agent_role='data-validator'/'compliance-reviewer'/'document-reviewer')。"
        "task 是子任务描述。"
        "subagent_type: 'query' = 只读查询, 'task' = 全部工具 (向后兼容)。"
        "agent_role: 指定专业角色 (优先于 subagent_type)，角色有工具白名单和专业 prompt。"
        "context 是传递给子智能体的上下文信息。"
        "inherit_context: 是否继承当前业务上下文 (默认 true)。"
    ),
    read_only=False,
)
async def spawn_subagent(
    task: str,  # 子任务描述
    subagent_type: str = "query",  # "query" = 只读查询, "task" = 全能执行
    context: str = "",  # 传递给子智能体的上下文
    agent_role: str = "",  # Phase 16: 专业角色名称
    inherit_context: bool = True,  # Phase 16: 是否继承业务上下文
) -> str:
    """派遣子智能体执行子任务，返回子智能体的最终回答。"""
    runner = _subagent_runner.get()
    if runner is None:
        return "错误: SubagentRunner 未初始化。"

    result = await runner.run_subagent(
        task=task,
        subagent_type=subagent_type,
        context=context,
        agent_role=agent_role,
        inherit_context=inherit_context,
    )
    return result
