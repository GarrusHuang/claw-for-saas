"""
子智能体运行器 — A3 动态化重构 + 3.3 生命周期增强。

主 Agent 通过 spawn_subagent / spawn_subagents 工具调用子智能体。
子智能体有独立的 AgenticRuntime 实例 + 独立上下文。

3.3 增强:
- start_subagent: 非阻塞启动，返回 agent_id
- wait_subagent: 等待子 Agent 完成
- send_to_subagent: 向运行中子 Agent 发送消息
- per-user 并发限制 (最多 3 个)
- 嵌套深度限制 (最多 3 层)
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from core.llm_client import LLMGatewayClient
from core.runtime import AgenticRuntime, RuntimeConfig
from core.tool_protocol import ToolCallParser
from core.tool_registry import ToolRegistry

if TYPE_CHECKING:
    from agent.prompt import PromptBuilder

logger = logging.getLogger(__name__)

# ── 3.3: 并发/深度限制 ──
_MAX_CONCURRENT_PER_USER = 3
_MAX_DEPTH = 3
_user_semaphores: dict[str, asyncio.Semaphore] = {}

# 默认子智能体系统 prompt
_DEFAULT_SUBAGENT_PROMPT = (
    "你是一个子智能体，负责执行分配的子任务。\n\n"
    "规则:\n"
    "1. 专注于完成分配的任务\n"
    "2. 使用可用工具高效执行\n"
    "3. 完成后输出清晰的结果\n"
)


@dataclass
class _RunningAgent:
    """运行中的子 Agent 状态。"""
    agent_id: str
    task: asyncio.Task
    inbox: asyncio.Queue
    user_id: str
    depth: int


def _get_user_semaphore(user_id: str) -> asyncio.Semaphore:
    """获取/创建 per-user 并发信号量。"""
    if user_id not in _user_semaphores:
        _user_semaphores[user_id] = asyncio.Semaphore(_MAX_CONCURRENT_PER_USER)
    return _user_semaphores[user_id]


class SubagentRunner:
    """
    子智能体运行器。

    为主 Agent 提供 spawn_subagent 能力:
    - 创建独立的 AgenticRuntime
    - 使用主 Agent 动态生成的 prompt 作为角色定义
    - 支持工具白名单过滤
    - 支持超时控制
    - 继承父级安全 hooks (pre_tool_use / post_tool_use)
    - 3.3: start/wait/send 生命周期管理
    """

    def __init__(
        self,
        llm_client: LLMGatewayClient,
        shared_registry: ToolRegistry,
        capability_registry: ToolRegistry,
        prompt_builder: PromptBuilder | None = None,
        hooks: Any | None = None,
        secret_redactor: Any | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.shared_registry = shared_registry
        self.capability_registry = capability_registry
        self.prompt_builder = prompt_builder
        self.hooks = hooks  # 继承父级安全 hooks
        self.secret_redactor = secret_redactor
        # 3.3: 运行中子 Agent 状态
        self._running: dict[str, _RunningAgent] = {}
        # #C: ToolRegistry 缓存 — 避免每次 merge
        self._merged_registry_cache: ToolRegistry | None = None

    async def run_subagent(
        self,
        task: str,
        prompt: str = "",
        tools: str = "",
        timeout_s: int = 120,
        inherit_context: bool = False,
    ) -> str:
        """
        执行子智能体 (同步等待模式，向下兼容)。

        Args:
            task: 子任务描述
            prompt: 动态角色 prompt（空则用默认）
            tools: 工具白名单，逗号分隔（空则继承全部）
            timeout_s: 超时秒数
            inherit_context: #8 是否 fork 父对话历史作为初始消息

        Returns:
            子智能体的最终回答文本
        """
        tool_registry = self._build_tool_registry(tools)
        system_prompt = self._build_system_prompt(prompt, tool_registry)
        initial_messages = self._get_parent_history() if inherit_context else None

        config = RuntimeConfig(
            max_iterations=15,
            max_tokens_per_turn=4096,
        )
        runtime = AgenticRuntime(
            llm_client=self.llm_client,
            tool_registry=tool_registry,
            tool_parser=ToolCallParser(),
            config=config,
            hooks=self.hooks,
            secret_redactor=self.secret_redactor,
        )

        try:
            coro = runtime.run(system_prompt, task, initial_messages=initial_messages)
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

    # ── 3.3: 非阻塞生命周期方法 ──

    async def start_subagent(
        self,
        task: str,
        prompt: str = "",
        tools: str = "",
        timeout_s: int = 120,
        depth: int = 0,
        user_id: str = "anonymous",
        inherit_context: bool = False,
    ) -> str:
        """
        非阻塞启动子 Agent，返回 agent_id。

        Args:
            task: 子任务描述
            prompt: 动态角色 prompt
            tools: 工具白名单
            timeout_s: 超时秒数
            depth: 当前嵌套深度
            user_id: 用于 per-user 并发控制
            inherit_context: #8 是否 fork 父对话历史

        Returns:
            agent_id 或错误信息 (以 "错误:" 开头)
        """
        # 深度检查
        if depth >= _MAX_DEPTH:
            return f"错误: 子 Agent 嵌套深度超限 (当前 {depth}, 最大 {_MAX_DEPTH})"

        # 并发检查
        sem = _get_user_semaphore(user_id)
        acquired = sem._value > 0  # 检查是否有可用槽位
        if not acquired:
            return f"错误: 用户 {user_id} 同时运行的子 Agent 已达上限 ({_MAX_CONCURRENT_PER_USER})"

        await sem.acquire()

        agent_id = f"sa_{secrets.token_hex(6)}"
        inbox: asyncio.Queue = asyncio.Queue()
        parent_history = self._get_parent_history() if inherit_context else None

        async def _run() -> str:
            try:
                tool_registry = self._build_tool_registry(tools)
                system_prompt = self._build_system_prompt(prompt, tool_registry)
                config = RuntimeConfig(max_iterations=15, max_tokens_per_turn=4096)
                runtime = AgenticRuntime(
                    llm_client=self.llm_client,
                    tool_registry=tool_registry,
                    tool_parser=ToolCallParser(),
                    config=config,
                    hooks=self.hooks,
                    secret_redactor=self.secret_redactor,
                    message_inbox=inbox,
                )
                coro = runtime.run(system_prompt, task, initial_messages=parent_history)
                result = await asyncio.wait_for(coro, timeout=timeout_s)
                return result.final_answer
            except asyncio.TimeoutError:
                return f"子智能体执行超时（{timeout_s}秒）。"
            except Exception as e:
                return f"子智能体执行失败: {e}"
            finally:
                sem.release()
                self._running.pop(agent_id, None)

        async_task = asyncio.create_task(_run())
        self._running[agent_id] = _RunningAgent(
            agent_id=agent_id,
            task=async_task,
            inbox=inbox,
            user_id=user_id,
            depth=depth,
        )

        logger.info(f"Started subagent {agent_id} (depth={depth}, user={user_id})")
        return agent_id

    async def wait_subagent(self, agent_id: str, timeout_s: float = 120) -> str:
        """
        等待子 Agent 完成，返回结果。

        Args:
            agent_id: 子 Agent ID
            timeout_s: 等待超时

        Returns:
            子 Agent 的最终回答或错误信息
        """
        running = self._running.get(agent_id)
        if running is None:
            return f"错误: 子 Agent {agent_id} 不存在或已完成"

        try:
            result = await asyncio.wait_for(running.task, timeout=timeout_s)
            return result
        except asyncio.TimeoutError:
            return f"等待子 Agent {agent_id} 超时（{timeout_s}秒）"

    async def send_to_subagent(self, agent_id: str, message: str) -> str:
        """
        向运行中的子 Agent 发送消息。

        Args:
            agent_id: 子 Agent ID
            message: 消息内容

        Returns:
            确认信息或错误
        """
        running = self._running.get(agent_id)
        if running is None:
            return f"错误: 子 Agent {agent_id} 不存在或已完成"

        if running.task.done():
            return f"错误: 子 Agent {agent_id} 已完成执行"

        await running.inbox.put(message)
        logger.info(f"Sent message to subagent {agent_id}")
        return f"消息已发送到子 Agent {agent_id}"

    def _get_parent_history(self) -> list[dict] | None:
        """
        #8: 获取父对话历史 (最近 10 轮 user/assistant 消息) 作为子 Agent 初始上下文。
        """
        try:
            from core.context import current_request
            ctx = current_request.get()
            if not ctx or not ctx.session_id:
                return None
            from dependencies import get_session_manager
            sm = get_session_manager()
            messages = sm.load_messages(ctx.tenant_id, ctx.user_id, ctx.session_id)
            # 过滤: 只保留 user/assistant 消息，跳过 system/tool
            filtered = [
                m for m in messages
                if m.get("role") in ("user", "assistant") and m.get("content")
            ]
            # 最近 10 轮
            return filtered[-20:] if len(filtered) > 20 else filtered
        except Exception as e:
            logger.debug(f"Failed to get parent history: {e}")
            return None

    def _build_tool_registry(self, tools: str) -> ToolRegistry:
        """
        构建子智能体的工具注册表。

        Args:
            tools: 逗号分隔的工具白名单，空则继承全部工具
        """
        # #C: 缓存 merged registry
        if self._merged_registry_cache is None:
            self._merged_registry_cache = self.shared_registry.merge(self.capability_registry)
        all_tools = self._merged_registry_cache

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
            logger.error(
                f"Tool whitelist matched nothing (requested: {tools}), "
                "returning empty registry — subagent will have no tools"
            )
            return filtered  # 不回退，返回空 registry 以尊重权限意图

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
