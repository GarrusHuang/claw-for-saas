"""
子智能体运行器 — A3 动态化重构。

主 Agent 通过 spawn_subagent / spawn_subagents 工具调用子智能体。
子智能体有独立的 AgenticRuntime 实例 + 独立上下文。

A3 改造:
- 去掉预定义角色文件 (agents/*.md) 和 AgentRoleLoader
- 去掉 query/task 双模式
- 主 Agent 动态传入 prompt 即角色
- 工具白名单通过逗号分隔字符串指定
- 支持超时控制
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from core.llm_client import LLMGatewayClient
from core.runtime import AgenticRuntime, RuntimeConfig
from core.tool_protocol import ToolCallParser
from core.tool_registry import ToolRegistry

if TYPE_CHECKING:
    from agent.prompt import PromptBuilder

logger = logging.getLogger(__name__)

# 默认子智能体系统 prompt
_DEFAULT_SUBAGENT_PROMPT = (
    "你是一个子智能体，负责执行分配的子任务。\n\n"
    "规则:\n"
    "1. 专注于完成分配的任务\n"
    "2. 使用可用工具高效执行\n"
    "3. 完成后输出清晰的结果\n"
)


class SubagentRunner:
    """
    子智能体运行器。

    为主 Agent 提供 spawn_subagent 能力:
    - 创建独立的 AgenticRuntime
    - 使用主 Agent 动态生成的 prompt 作为角色定义
    - 支持工具白名单过滤
    - 支持超时控制
    """

    def __init__(
        self,
        llm_client: LLMGatewayClient,
        shared_registry: ToolRegistry,
        capability_registry: ToolRegistry,
        prompt_builder: PromptBuilder | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.shared_registry = shared_registry
        self.capability_registry = capability_registry
        self.prompt_builder = prompt_builder

    async def run_subagent(
        self,
        task: str,
        prompt: str = "",
        tools: str = "",
        timeout_s: int = 120,
    ) -> str:
        """
        执行子智能体。

        Args:
            task: 子任务描述
            prompt: 动态角色 prompt（空则用默认）
            tools: 工具白名单，逗号分隔（空则继承全部）
            timeout_s: 超时秒数

        Returns:
            子智能体的最终回答文本
        """
        # 构建工具集
        tool_registry = self._build_tool_registry(tools)

        # 构建系统 prompt
        system_prompt = self._build_system_prompt(prompt, tool_registry)

        # 运行
        config = RuntimeConfig(
            max_iterations=15,
            max_tokens_per_turn=4096,
        )
        runtime = AgenticRuntime(
            llm_client=self.llm_client,
            tool_registry=tool_registry,
            tool_parser=ToolCallParser(),
            config=config,
        )

        try:
            coro = runtime.run(system_prompt, task)
            result = await asyncio.wait_for(coro, timeout=timeout_s)
            logger.info(
                f"Subagent completed: {result.iterations} iterations, "
                f"{result.tool_call_count} tool calls"
            )
            return result.final_answer
        except asyncio.TimeoutError:
            logger.warning(f"Subagent timed out after {timeout_s}s")
            return f"子智能体执行超时（{timeout_s}秒）。"
        except Exception as e:
            logger.error(f"Subagent failed: {e}")
            return f"子智能体执行失败: {e}"

    def _build_tool_registry(self, tools: str) -> ToolRegistry:
        """
        构建子智能体的工具注册表。

        Args:
            tools: 逗号分隔的工具白名单，空则继承全部工具
        """
        all_tools = self.shared_registry.merge(self.capability_registry)

        if not tools.strip():
            return all_tools

        # 白名单过滤
        tool_names = [t.strip() for t in tools.split(",") if t.strip()]
        filtered = ToolRegistry()

        for tool_name in tool_names:
            tool = all_tools.get_tool(tool_name)
            if tool:
                filtered.register(
                    func=tool.func,
                    description=tool.description,
                    read_only=tool.read_only,
                    name=tool.name,
                )
            else:
                logger.debug(f"Tool '{tool_name}' not found in registry, skipping")

        if len(filtered) == 0:
            logger.warning("Tool whitelist matched nothing, falling back to all tools")
            return all_tools

        return filtered

    def _build_system_prompt(self, prompt: str, tool_registry: ToolRegistry) -> str:
        """构建子智能体的系统提示。"""
        # 基础 prompt (minimal 模式)
        minimal_base = ""
        if self.prompt_builder:
            minimal_base = self.prompt_builder.build_system_prompt(mode="minimal")

        parts = []
        if minimal_base:
            parts.append(minimal_base)

        # 动态 prompt 或默认
        parts.append(prompt if prompt.strip() else _DEFAULT_SUBAGENT_PROMPT)

        # 列出可用工具
        tool_names_list = tool_registry.get_tool_names()
        if tool_names_list:
            parts.append(f"\n## 可用工具\n{', '.join(tool_names_list)}")

        return "\n".join(parts)
