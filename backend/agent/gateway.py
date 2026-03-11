"""
Agent Gateway — 对标 OpenClaw Gateway / Claude Code Agent Loop。

替代 Orchestrator + Pipeline:
- 没有固定步骤编排
- Agent 自主决定调用什么工具、什么顺序
- 通过 8 层 prompt 注入知识和约束
- 双模式: AUTO (Agent 自主判断) / EXECUTE (用户确认后执行)
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from core.context import (
    current_event_bus, current_session_id, current_user_id,
    current_skill_loader, current_file_service, current_browser_service,
    current_known_field_ids, current_business_context,
    current_plan_tracker,
    current_learning_memory, current_correction_memory,
)
from core.event_bus import EventBus
from core.llm_client import LLMGatewayClient
from core.runtime import AgenticRuntime, RuntimeConfig, RuntimeResult
from core.tool_protocol import ToolCallParser
from core.tool_registry import ToolRegistry

from agent.hooks import HookRegistry, build_default_hooks
from agent.prompt import PromptBuilder
from agent.session import SessionManager
from agent.subagent import SubagentRunner

logger = logging.getLogger(__name__)


class AgentGateway:
    """
    Agent Gateway — 单一入口处理所有用户请求。

    双模式:
    - AUTO (plan_mode=True): Agent 自主判断是否需要用户确认
    - EXECUTE (plan_mode=False): 用户已确认方案，直接执行
    """

    def __init__(
        self,
        *,
        llm_client: LLMGatewayClient,
        tool_registry: ToolRegistry,
        execute_registry: ToolRegistry | None = None,
        session_manager: SessionManager,
        skill_loader: Any,  # SkillLoader
        prompt_builder: PromptBuilder,
        subagent_runner: SubagentRunner,
        correction_memory: Any,  # CorrectionMemory
        learning_memory: Any,  # LearningMemory
        hooks: HookRegistry | None = None,
        runtime_config: RuntimeConfig | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.tool_registry = tool_registry  # AUTO: 33 tools (含 propose_plan)
        self.execute_registry = execute_registry or tool_registry  # EXECUTE: 32 tools (无 propose_plan)
        self.session_manager = session_manager
        self.skill_loader = skill_loader
        self.prompt_builder = prompt_builder
        self.subagent_runner = subagent_runner
        self.correction_memory = correction_memory
        self.learning_memory = learning_memory
        self.hooks = hooks or build_default_hooks()
        self.runtime_config = runtime_config or RuntimeConfig(
            max_iterations=25,
            max_tokens_per_turn=4096,
        )

    async def chat(
        self,
        *,
        user_id: str = "U001",
        session_id: str | None = None,
        message: str,
        business_type: str,
        business_context: dict | None = None,
        skill_names: list[str] | None = None,
        event_bus: EventBus | None = None,
        plan_mode: bool = True,
    ) -> dict:
        """
        处理用户消息 — 单一入口。

        Args:
            user_id: 用户 ID (隔离)
            session_id: 可选, 续接会话
            message: 用户消息
            business_type: 业务类型 (reimbursement_create 等)
            business_context: 业务上下文 (form_fields, audit_rules 等)
            skill_names: 要加载的 Skills
            event_bus: SSE 事件总线
            plan_mode: True=AUTO(自主模式), False=EXECUTE(执行模式)

        Returns:
            {"session_id": str, "answer": str, "iterations": int, ...}
        """
        start_time = time.time()

        # ── 1. 设置 contextvars ──
        if event_bus:
            current_event_bus.set(event_bus)
        current_user_id.set(user_id)

        # 注入 SubagentRunner 到 contextvars
        from tools.capabilities.subagent_tools import _subagent_runner
        _subagent_runner.set(self.subagent_runner)

        # Phase 13: 注入 ParallelReviewOrchestrator 到 contextvars
        from agent.parallel_review import ParallelReviewOrchestrator
        from tools.capabilities.review_tools import _review_orchestrator
        _review_orchestrator.set(ParallelReviewOrchestrator(self.subagent_runner))

        # 注入 SkillLoader 到 contextvars (供 skill 管理工具使用)
        if self.skill_loader:
            current_skill_loader.set(self.skill_loader)

        # 注入 FileService 到 contextvars (供文件工具使用)
        try:
            from dependencies import get_file_service
            current_file_service.set(get_file_service())
        except Exception:
            pass  # FileService 可选，不阻塞启动

        # 注入 BrowserService 到 contextvars (供浏览器工具使用)
        try:
            from dependencies import get_browser_service
            current_browser_service.set(get_browser_service())
        except Exception:
            pass  # BrowserService 可选，不阻塞启动

        # 注入 known_field_ids 到 contextvars (供 known_values_guard hook 使用)
        current_known_field_ids.set(set())  # 始终初始化，避免 LookupError
        if business_context and business_context.get("known_values"):
            kv = business_context["known_values"]
            if isinstance(kv, dict):
                current_known_field_ids.set(set(kv.keys()))
            elif isinstance(kv, list):
                ids = {
                    item.get("field_id")
                    for item in kv
                    if isinstance(item, dict) and "field_id" in item
                }
                current_known_field_ids.set(ids)

        # Phase 16: 注入 business_context 到 ContextVar (供子智能体继承)
        if business_context:
            current_business_context.set(business_context)

        # Phase 28: 注入 Memory 到 ContextVar (供记忆工具使用)
        current_learning_memory.set(self.learning_memory)
        current_correction_memory.set(self.correction_memory)

        # ── 2. 解析/创建会话 ──
        if session_id and self.session_manager.session_exists(user_id, session_id):
            logger.info(f"Resuming session: {session_id}")
        else:
            session_id = self.session_manager.create_session(
                user_id, {"business_type": business_type}
            )
            logger.info(f"New session: {session_id}")

        current_session_id.set(session_id)

        # 发射 session 事件
        if event_bus:
            event_bus.emit("pipeline_started", {
                "session_id": session_id,
                "business_type": business_type,
            })

        # ── 3. 加载会话历史 ──
        history_messages = self.session_manager.load_messages(user_id, session_id)

        # ── 4. 加载 Skills ──
        skill_knowledge = ""

        if self.skill_loader:
            # 场景推断
            scenario = business_type  # e.g. "reimbursement_create"
            bt = business_type.split("_")[0] if "_" in business_type else business_type

            try:
                # 加载领域知识
                skill_knowledge = self.skill_loader.load_for_pipeline(
                    scenario=scenario,
                    agent_name="universal",
                    business_type=bt,
                )
            except Exception as e:
                logger.warning(f"Skill loading failed: {e}")

        # ── 5. 构建 Memory 上下文 ──
        memory_parts: list[str] = []

        if self.correction_memory:
            try:
                bt = business_type.split("_")[0] if "_" in business_type else business_type
                prefs = self.correction_memory.build_preference_prompt(
                    user_id=user_id,
                    business_type=bt,
                    doc_type=bt,
                )
                if prefs:
                    memory_parts.append(f"[用户偏好]\n{prefs}")
            except Exception as e:
                logger.warning(f"CorrectionMemory error: {e}")

        if self.learning_memory:
            try:
                exp = self.learning_memory.build_experience_prompt(
                    scenario=business_type,
                    business_type=business_type.split("_")[0] if "_" in business_type else business_type,
                )
                if exp:
                    memory_parts.append(f"[历史经验]\n{exp}")
            except Exception as e:
                logger.warning(f"LearningMemory error: {e}")

        memory_context = "\n\n".join(memory_parts) if memory_parts else ""

        # ── 6. 构建 8 层系统提示 ──
        from agent.prompt import ToolSummary
        tool_summaries = [
            ToolSummary(
                name=t.name,
                description=t.description,
                read_only=t.read_only,
            )
            for t in self.tool_registry.list_tools()
        ]

        system_prompt = self.prompt_builder.build_system_prompt(
            skill_knowledge=skill_knowledge,
            business_context=business_context,
            memory_context=memory_context,
            user_id=user_id,
            session_id=session_id,
            plan_mode=plan_mode,
            tool_summaries=tool_summaries,
        )

        # ── 7. 构建用户消息 ──
        materials_summary = ""
        if business_context and business_context.get("materials"):
            materials = business_context["materials"]
            summaries = []
            for m in materials:
                if isinstance(m, dict):
                    content = m.get("content", "")
                    filename = m.get("filename", "")
                    summaries.append(f"[{filename}]\n{content[:2000]}")
            materials_summary = "\n\n".join(summaries)

        user_message = self.prompt_builder.build_user_message(
            message=message,
            materials_summary=materials_summary,
        )

        # ── 8. 工具集 — 根据模式选择 ──
        if plan_mode:
            tools = self.tool_registry  # AUTO: 33 tools (含 propose_plan)
        else:
            tools = self.execute_registry  # EXECUTE: 32 tools (无 propose_plan)

            # EXECUTE 模式: 从 session 中恢复 PlanTracker
            self._rebuild_plan_tracker(user_id, session_id, event_bus)

        # ── 9. 创建 AgenticRuntime 并执行 ──
        runtime = AgenticRuntime(
            llm_client=self.llm_client,
            tool_registry=tools,
            tool_parser=ToolCallParser(),
            config=self.runtime_config,
            event_bus=event_bus,
            trace_id=event_bus.trace_id if event_bus else "",
            hooks=self.hooks,
        )

        # 构建初始消息 (对话历史)
        initial_messages = None
        if history_messages:
            initial_messages = history_messages

        try:
            result: RuntimeResult = await runtime.run(
                system_prompt=system_prompt,
                user_message=user_message,
                initial_messages=initial_messages,
            )
        except Exception as e:
            logger.error(f"AgenticRuntime failed: {e}")
            if event_bus:
                event_bus.emit("error", {
                    "code": "RUNTIME_ERROR",
                    "message": str(e),
                    "recoverable": False,
                })
            return {
                "session_id": session_id,
                "answer": f"执行失败: {e}",
                "error": str(e),
            }

        # ── 10. 持久化会话 ──
        self.session_manager.append_message(
            user_id, session_id,
            {"role": "user", "content": message, "ts": start_time},
        )
        self.session_manager.append_message(
            user_id, session_id,
            {"role": "assistant", "content": result.final_answer, "ts": time.time()},
        )

        # 上下文压缩检查
        history = self.session_manager.load_messages(user_id, session_id)
        if len(history) > 20:
            try:
                await self.session_manager.compact(user_id, session_id, self.llm_client)
            except Exception as e:
                logger.warning(f"Session compaction failed: {e}")

        # ── 11. 发射 Agent 文字回复 ──
        # text_delta 事件已在 runtime 流式发射，这里发完整版做兜底
        if result.final_answer and event_bus:
            event_bus.emit("agent_message", {
                "content": result.final_answer,
            })

        # 发射 thinking 汇总 (如果有且前端开启了展示思考)
        if result.thinking and event_bus:
            event_bus.emit("thinking_complete", {
                "content": result.thinking,
            })

        # ── 12. 触发 agent_stop hook ──
        if self.hooks:
            from agent.hooks import HookEvent
            stop_event = HookEvent(
                event_type="agent_stop",
                session_id=session_id,
                user_id=user_id,
                runtime_steps=[
                    {"tool": s.tool_name, "args": s.tool_args, "result": s.tool_result}
                    for s in result.steps
                    if s.tool_name
                ],
                context={
                    "final_answer": result.final_answer,
                    "iterations": result.iterations,
                    "business_type": business_type,
                },
            )
            try:
                await self.hooks.fire(stop_event)
            except Exception as e:
                logger.warning(f"agent_stop hook error: {e}")

        # ── 13. 检测 plan_awaiting_approval ──
        is_plan_awaiting = self._check_plan_awaiting(event_bus)

        # ── 13.5. PlanTracker 收尾 ──
        tracker = current_plan_tracker.get(None)
        if tracker:
            if result.error:
                tracker.fail_current()
            elif not is_plan_awaiting:
                tracker.complete_all()

        # ── 13.6. 持久化 plan steps 到 session (供 EXECUTE 模式恢复) ──
        if is_plan_awaiting:
            for evt in event_bus.history if event_bus else []:
                if evt.event_type == "plan_proposed":
                    steps = evt.data.get("steps", [])
                    if steps:
                        self.session_manager.save_plan_steps(user_id, session_id, steps)
                    break

        # ── 13.7. 记录成功经验到 LearningMemory ──
        if (
            self.learning_memory
            and not is_plan_awaiting
            and not result.error
            and not result.max_iterations_reached
        ):
            try:
                tool_chain = [s.tool_name for s in result.steps if s.tool_name]
                bt = business_type.split("_")[0] if "_" in business_type else business_type
                self.learning_memory.record_success(
                    scenario=business_type,
                    business_type=bt,
                    doc_type=(business_context or {}).get("doc_type", ""),
                    description=f"{business_type} 成功完成",
                    success_pattern={"tool_chain": tool_chain},
                    correction_count=0,
                )
            except Exception as e:
                logger.warning(f"Failed to record learning experience: {e}")

        # ── 14. 发射完成事件 ──
        duration_ms = (time.time() - start_time) * 1000
        if event_bus:
            if is_plan_awaiting:
                status = "plan_awaiting_approval"
            elif result.error:
                status = "failed"
            else:
                status = "success"

            event_bus.emit("pipeline_complete", {
                "status": status,
                "duration_ms": round(duration_ms, 1),
                "summary": {
                    "iterations": result.iterations,
                    "tool_calls": result.tool_call_count,
                    "max_iterations_reached": result.max_iterations_reached,
                    "session_id": session_id,
                },
            })

        return {
            "session_id": session_id,
            "answer": result.final_answer,
            "iterations": result.iterations,
            "tool_calls": result.tool_call_count,
            "duration_ms": round(duration_ms, 1),
            "max_iterations_reached": result.max_iterations_reached,
        }

    def _rebuild_plan_tracker(
        self,
        user_id: str,
        session_id: str,
        event_bus: EventBus | None,
    ) -> None:
        """EXECUTE 模式: 从 session 中读取 plan steps, 重建 PlanTracker。"""
        from agent.plan_tracker import PlanTracker

        steps = self.session_manager.load_plan_steps(user_id, session_id)
        if steps:
            tracker = PlanTracker(steps, event_bus=event_bus)
            current_plan_tracker.set(tracker)
            # 推送 steps 给前端初始化 todo list
            if event_bus:
                event_bus.emit("plan_steps_init", {"steps": steps})
            logger.info(f"Rebuilt PlanTracker with {len(steps)} steps for EXECUTE mode")

    def _check_plan_awaiting(self, event_bus: EventBus | None) -> bool:
        """检查 EventBus 历史中是否有 requires_approval=True 的 plan_proposed 事件。"""
        if not event_bus:
            return False
        for evt in event_bus.history:
            if evt.event_type == "plan_proposed" and evt.data.get("requires_approval"):
                return True
        return False
