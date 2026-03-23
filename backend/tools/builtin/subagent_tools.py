"""
子智能体工具 — A3 动态化重构 + 3.3 生命周期增强。

主 Agent 通过 spawn_subagent / spawn_subagents 调用子智能体。
子智能体有独立的 AgenticRuntime 实例和独立上下文。

3.3 增强:
- spawn_subagent(wait=False): 非阻塞启动，返回 agent_id
- wait_subagent: 等待子 Agent 完成
- send_to_subagent: 向运行中子 Agent 发消息
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
        "wait: 是否等待完成（默认 True）。False 时立即返回 agent_id，后续用 wait_subagent 获取结果。"
        "inherit_context: 是否继承父对话历史（默认 False）。True 时子 Agent 可看到之前的对话内容。"
    ),
    read_only=False,
)
async def spawn_subagent(
    task: str,  # 子任务描述
    prompt: str = "",  # 动态角色 prompt
    tools: str = "",  # 工具白名单，逗号分隔
    timeout_s: int = 120,  # 超时秒数
    wait: bool = True,  # 3.3: 是否等待完成
    inherit_context: bool = False,  # #8: fork 父对话历史
) -> str:
    """派遣子智能体执行子任务。wait=True 返回结果，wait=False 返回 agent_id。"""
    ctx = get_request_context()
    runner = ctx.subagent_runner
    if runner is None:
        return "错误: SubagentRunner 未初始化。"

    if wait:
        result = await runner.run_subagent(
            task=task,
            prompt=prompt,
            tools=tools,
            timeout_s=timeout_s,
            inherit_context=inherit_context,
        )
        return result
    else:
        agent_id = await runner.start_subagent(
            task=task,
            prompt=prompt,
            tools=tools,
            timeout_s=timeout_s,
            depth=ctx.subagent_depth + 1,
            user_id=ctx.user_id,
            inherit_context=inherit_context,
        )
        return agent_id


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
    """批量并行派遣多个子智能体 (内部使用 start+wait 模式)，返回汇总结果。"""
    ctx = get_request_context()
    runner = ctx.subagent_runner
    if runner is None:
        return "错误: SubagentRunner 未初始化。"

    try:
        task_list = json.loads(tasks)
        if not isinstance(task_list, list) or len(task_list) == 0:
            return "错误: tasks 必须是非空 JSON 数组。"
    except json.JSONDecodeError as e:
        return f"错误: tasks JSON 解析失败: {e}"

    # #B: 用 start+wait 替代直接 run_subagent，复用并发控制
    agent_ids: list[tuple[str, dict]] = []
    for item in task_list:
        if isinstance(item, str):
            item = {"task": item}
        if not isinstance(item, dict) or "task" not in item:
            return "错误: tasks 数组每项必须包含 task 字段。"
        agent_id = await runner.start_subagent(
            task=item["task"],
            prompt=item.get("prompt", ""),
            tools=item.get("tools", ""),
            timeout_s=timeout_s,
            depth=ctx.subagent_depth + 1,
            user_id=ctx.user_id,
        )
        agent_ids.append((agent_id, item))

    # 并行等待所有结果
    async def _wait(aid: str) -> str:
        if aid.startswith("错误:"):
            return aid
        return await runner.wait_subagent(aid, timeout_s=timeout_s)

    results = await asyncio.gather(*[_wait(aid) for aid, _ in agent_ids])

    parts = []
    for i, ((aid, item), result) in enumerate(zip(agent_ids, results)):
        task_desc = item["task"] if isinstance(item, dict) else item
        parts.append(f"## 子任务 {i+1}: {task_desc}\n{result}")

    return "\n\n".join(parts)


# ── 3.3: 新工具 ──

@subagent_capability_registry.tool(
    description=(
        "等待子 Agent 完成并获取结果。"
        "agent_id: spawn_subagent(wait=False) 返回的子 Agent ID。"
        "timeout_s: 等待超时秒数（默认 120）。"
    ),
    read_only=False,
)
async def wait_subagent(
    agent_id: str,  # 子 Agent ID
    timeout_s: int = 120,  # 等待超时
) -> str:
    """等待子 Agent 完成，返回结果。"""
    runner = get_request_context().subagent_runner
    if runner is None:
        return "错误: SubagentRunner 未初始化。"

    return await runner.wait_subagent(agent_id, timeout_s=timeout_s)


@subagent_capability_registry.tool(
    description=(
        "向运行中的子 Agent 发送消息。消息会作为 user message 注入子 Agent 的 ReAct 循环。"
        "agent_id: 子 Agent ID。"
        "message: 要发送的消息内容。"
    ),
    read_only=False,
)
async def send_to_subagent(
    agent_id: str,  # 子 Agent ID
    message: str,  # 消息内容
) -> str:
    """向运行中的子 Agent 发送消息。"""
    runner = get_request_context().subagent_runner
    if runner is None:
        return "错误: SubagentRunner 未初始化。"

    return await runner.send_to_subagent(agent_id, message)
