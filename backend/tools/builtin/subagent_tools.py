"""
子智能体工具 — A3 动态化重构。

主 Agent 通过 spawn_subagent / spawn_subagents 调用子智能体。
子智能体有独立的 AgenticRuntime 实例和独立上下文。

A3 改造:
- 去掉预定义角色 (agents/*.md) 和 subagent_type (query/task)
- 主 Agent 动态生成 prompt 即角色
- 支持工具白名单 (逗号分隔)
- 支持批量并行 (spawn_subagents)
"""

from __future__ import annotations

import asyncio
import json

from core.context import get_request_context
from core.tool_registry import ToolRegistry

subagent_capability_registry = ToolRegistry()


@subagent_capability_registry.tool(
    description=(
        "派遣子智能体执行子任务。子智能体有独立上下文，完成后返回结果。"
        "task: 子任务描述（必填）。"
        "prompt: 子智能体的角色/行为 prompt（可选，不填则用默认通用 prompt）。"
        "tools: 工具白名单，逗号分隔（可选，不填则继承全部工具）。"
        "timeout_s: 超时秒数（默认 120）。"
    ),
    read_only=False,
)
async def spawn_subagent(
    task: str,  # 子任务描述
    prompt: str = "",  # 动态角色 prompt
    tools: str = "",  # 工具白名单，逗号分隔
    timeout_s: int = 120,  # 超时秒数
) -> str:
    """派遣子智能体执行子任务，返回子智能体的最终回答。"""
    runner = get_request_context().subagent_runner
    if runner is None:
        return "错误: SubagentRunner 未初始化。"

    result = await runner.run_subagent(
        task=task,
        prompt=prompt,
        tools=tools,
        timeout_s=timeout_s,
    )
    return result


@subagent_capability_registry.tool(
    description=(
        "批量并行派遣多个子智能体。所有子智能体同时执行，全部完成后返回汇总结果。"
        "tasks: JSON 数组，每项包含 task(必填)、prompt(可选)、tools(可选)。"
        "示例: [{\"task\":\"检查数据\",\"prompt\":\"你是数据验证专家\"},{\"task\":\"检查合规\"}]"
        "timeout_s: 所有子智能体的超时秒数（默认 120）。"
    ),
    read_only=False,
)
async def spawn_subagents(
    tasks: str,  # JSON 数组
    timeout_s: int = 120,
) -> str:
    """批量并行派遣多个子智能体，返回汇总结果。"""
    runner = get_request_context().subagent_runner
    if runner is None:
        return "错误: SubagentRunner 未初始化。"

    # 解析 tasks JSON
    try:
        task_list = json.loads(tasks)
        if not isinstance(task_list, list) or len(task_list) == 0:
            return "错误: tasks 必须是非空 JSON 数组。"
    except json.JSONDecodeError as e:
        return f"错误: tasks JSON 解析失败: {e}"

    # 并行执行
    coros = []
    for item in task_list:
        if isinstance(item, str):
            item = {"task": item}
        if not isinstance(item, dict) or "task" not in item:
            return "错误: tasks 数组每项必须包含 task 字段。"
        coros.append(
            runner.run_subagent(
                task=item["task"],
                prompt=item.get("prompt", ""),
                tools=item.get("tools", ""),
                timeout_s=timeout_s,
            )
        )

    results = await asyncio.gather(*coros, return_exceptions=True)

    # 格式化结果
    parts = []
    for i, (item, result) in enumerate(zip(task_list, results)):
        task_desc = item["task"] if isinstance(item, dict) else item
        if isinstance(result, Exception):
            parts.append(f"## 子任务 {i+1}: {task_desc}\n**错误**: {result}")
        else:
            parts.append(f"## 子任务 {i+1}: {task_desc}\n{result}")

    return "\n\n".join(parts)
