"""
子智能体运行器 — 对标 Claude Code 的 Subagent 系统。

主 Agent 通过 spawn_subagent 工具调用子智能体。
子智能体有独立的 AgenticRuntime 实例 + 独立上下文。

子智能体类型 (向后兼容):
- query: 只用只读工具 (MCP查询 + calculator)，适合数据收集
- task: 用全部工具，适合具体执行子任务

Phase 16 新增 — 角色模式:
- 指定 agent_role (如 "data-validator") → 加载角色定义 → 白名单工具 + 专业 prompt
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, TYPE_CHECKING

from core.llm_client import LLMGatewayClient
from core.runtime import AgenticRuntime, RuntimeConfig
from core.tool_protocol import ToolCallParser
from core.tool_registry import ToolRegistry

if TYPE_CHECKING:
    from agent.prompt import PromptBuilder

logger = logging.getLogger(__name__)

# agents/ 目录的默认路径
_DEFAULT_AGENTS_DIR = Path(__file__).parent.parent / "agents"


class SubagentRunner:
    """
    子智能体运行器。

    为主 Agent 提供 spawn_subagent 能力:
    - 创建独立的 AgenticRuntime
    - 构建简化版 system prompt (或基于角色定义)
    - 执行 ReAct 循环
    - 返回结果文本给主 Agent

    Phase 16 新增:
    - agent_role: 指定角色 → 加载 agents/{role}.md
    - 工具白名单: 角色定义中的 allowed_tools
    - 上下文继承: inherit_context=True → 注入 business_context
    """

    def __init__(
        self,
        llm_client: LLMGatewayClient,
        shared_registry: ToolRegistry,
        capability_registry: ToolRegistry,
        agents_dir: Path | str | None = None,
        prompt_builder: PromptBuilder | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.shared_registry = shared_registry  # 12 个只读工具
        self.capability_registry = capability_registry  # 14 个能力工具
        self.agents_dir = Path(agents_dir) if agents_dir else _DEFAULT_AGENTS_DIR
        self.prompt_builder = prompt_builder
        self._role_loader: Any = None  # lazy init

    @property
    def role_loader(self):
        """懒加载 AgentRoleLoader。"""
        if self._role_loader is None:
            from agent.agent_roles import AgentRoleLoader
            self._role_loader = AgentRoleLoader(self.agents_dir)
        return self._role_loader

    async def run_subagent(
        self,
        task: str,
        subagent_type: str = "query",
        context: str = "",
        agent_role: str = "",
        inherit_context: bool = True,
    ) -> str:
        """
        执行子智能体。

        Args:
            task: 子任务描述
            subagent_type: "query" (只读) 或 "task" (全能) — 向后兼容
            context: 从主 Agent 传递的上下文
            agent_role: Phase 16 角色名称 (如 "data-validator")
            inherit_context: 是否继承主 Agent 的 business_context

        Returns:
            子智能体的最终回答文本
        """
        # Phase 16: 角色模式优先
        if agent_role:
            return await self._run_with_role(task, agent_role, context, inherit_context)

        # 向后兼容: query/task 模式
        return await self._run_legacy(task, subagent_type, context, inherit_context)

    async def _run_with_role(
        self, task: str, agent_role: str, context: str, inherit_context: bool
    ) -> str:
        """使用角色定义运行子智能体。"""
        try:
            role = self.role_loader.load_role(agent_role)
        except ValueError as e:
            return f"错误: {e}"

        # 构建白名单工具集
        tools = self._build_filtered_registry(role.allowed_tools)

        if len(tools) == 0:
            logger.warning(f"Role '{agent_role}' has no matching tools, falling back to shared")
            tools = self.shared_registry

        # 构建系统提示
        system_prompt = self._build_role_prompt(role, context, inherit_context)

        # 运行
        config = RuntimeConfig(
            max_iterations=role.max_iterations,
            max_tokens_per_turn=4096,
        )
        runtime = AgenticRuntime(
            llm_client=self.llm_client,
            tool_registry=tools,
            tool_parser=ToolCallParser(),
            config=config,
        )

        try:
            result = await runtime.run(system_prompt, task)
            logger.info(
                f"Subagent (role={agent_role}) completed: "
                f"{result.iterations} iterations, {result.tool_call_count} tool calls"
            )
            return result.final_answer
        except Exception as e:
            logger.error(f"Subagent (role={agent_role}) failed: {e}")
            return f"子智能体执行失败: {e}"

    async def _run_legacy(
        self, task: str, subagent_type: str, context: str, inherit_context: bool
    ) -> str:
        """向后兼容: query/task 模式。"""
        # 选择工具集
        if subagent_type == "query":
            tools = self.shared_registry  # 只读工具
            max_iter = 8
        else:
            tools = self.shared_registry.merge(self.capability_registry)
            max_iter = 12

        # 构建子 Agent 的 system prompt
        system_prompt = self._build_subagent_prompt(subagent_type, context, inherit_context)

        # 创建独立的 AgenticRuntime (无 EventBus = 不发 SSE)
        config = RuntimeConfig(
            max_iterations=max_iter,
            max_tokens_per_turn=4096,
        )
        runtime = AgenticRuntime(
            llm_client=self.llm_client,
            tool_registry=tools,
            tool_parser=ToolCallParser(),
            config=config,
        )

        try:
            result = await runtime.run(system_prompt, task)
            logger.info(
                f"Subagent ({subagent_type}) completed: "
                f"{result.iterations} iterations, {result.tool_call_count} tool calls"
            )
            return result.final_answer
        except Exception as e:
            logger.error(f"Subagent failed: {e}")
            return f"子智能体执行失败: {e}"

    def _build_filtered_registry(self, allowed_tools: list[str]) -> ToolRegistry:
        """构建工具白名单过滤后的注册表。"""
        filtered = ToolRegistry()
        all_tools = self.shared_registry.merge(self.capability_registry)

        for tool_name in allowed_tools:
            tool = all_tools.get_tool(tool_name)
            if tool:
                filtered.register(
                    func=tool.func,
                    description=tool.description,
                    read_only=tool.read_only,
                    name=tool.name,
                )
            else:
                logger.debug(f"Tool '{tool_name}' in whitelist not found in registry, skipping")

        return filtered

    def _build_minimal_base(self) -> str:
        """使用 PromptBuilder minimal 模式构建基础 prompt。"""
        if self.prompt_builder is None:
            return ""
        return self.prompt_builder.build_system_prompt(mode="minimal")

    def _build_role_prompt(
        self, role: Any, context: str, inherit_context: bool
    ) -> str:
        """基于角色定义构建系统提示。"""
        minimal_base = self._build_minimal_base()
        parts = [minimal_base] if minimal_base else []
        parts.append(role.system_prompt)

        # 列出可用工具
        if role.allowed_tools:
            tools_str = ", ".join(role.allowed_tools)
            parts.append(f"\n## 可用工具\n{tools_str}")

        # 上下文继承
        if inherit_context:
            biz_ctx = self._get_business_context()
            if biz_ctx:
                parts.append(f"\n<business_context>\n{biz_ctx}\n</business_context>")

        # 显式传递的上下文
        if context:
            parts.append(f"\n<context>\n{context}\n</context>")

        return "\n".join(parts)

    def _build_subagent_prompt(
        self, subagent_type: str, context: str, inherit_context: bool
    ) -> str:
        """构建子 Agent 专用 prompt (简化版, 向后兼容)。"""
        minimal_base = self._build_minimal_base()
        if subagent_type == "query":
            prompt = (
                "你是一个数据查询助手。你的任务是使用工具查询数据并汇总结果。\n\n"
                "可用工具:\n"
                "- get_user_profile: 查询用户信息 (参数: user_id)\n"
                "- get_expense_standards: 查询费用标准 (参数: city, level)\n"
                "- get_budget_balance: 查询预算余额 (参数: department_id)\n"
                "- verify_invoice: 发票验真\n"
                "- get_contract_template: 获取合同模板\n"
                "- get_supplier_info: 查询供应商信息\n"
                "- calculator 系列: 数值计算\n\n"
                "规则:\n"
                "1. user_id 使用系统 ID (如 'U001')，不要用姓名\n"
                "2. 数值比较必须使用 calculator 工具\n"
                "3. 完成查询后直接输出结构化结果\n"
            )
        else:
            prompt = (
                "你是一个任务执行助手。你的任务是使用工具完成分配的子任务。\n\n"
                "规则:\n"
                "1. user_id 使用系统 ID (如 'U001')\n"
                "2. 数值比较必须使用 calculator 工具\n"
                "3. 高效执行，完成后输出结果\n"
            )

        # Phase 16: 上下文继承
        if inherit_context:
            biz_ctx = self._get_business_context()
            if biz_ctx:
                prompt += f"\n<business_context>\n{biz_ctx}\n</business_context>"

        if context:
            prompt += f"\n<context>\n{context}\n</context>"

        if minimal_base:
            return minimal_base + "\n" + prompt
        return prompt

    def _get_business_context(self) -> str:
        """从 ContextVar 获取当前业务上下文。"""
        try:
            from core.context import current_business_context
            ctx = current_business_context.get()
            if ctx:
                import json
                return json.dumps(ctx, ensure_ascii=False, indent=2)[:3000]
        except Exception:
            pass
        return ""

    def get_available_roles(self) -> list[str]:
        """列出所有可用的 Agent 角色。"""
        return self.role_loader.list_roles()
