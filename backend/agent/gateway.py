"""
Agent Gateway — 对标 OpenClaw Gateway / Claude Code Agent Loop。

A2 简化:
- 去掉 business_context 推送 (MCP 拉取模式)
- 去掉 plan_mode 双模式 (Plan 纯进度展示)
- 单一工具集，Agent 自主决策
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import mimetypes

from core.context import (
    current_event_bus, current_session_id, current_user_id,
    current_tenant_id,
    current_skill_loader, current_file_service, current_browser_service,
    current_plan_tracker,
    current_memory_store,
    current_known_field_ids,
    current_sandbox, current_data_lock,
    current_mcp_provider,
    current_scheduler,
)
from core.event_bus import EventBus
from core.llm_client import LLMGatewayClient
from core.runtime import AgenticRuntime, RuntimeConfig, RuntimeResult, StepType
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

    Agent 自主决策，通过 propose_plan 记录计划进度（纯展示，无审批）。
    """

    def __init__(
        self,
        *,
        llm_client: LLMGatewayClient,
        tool_registry: ToolRegistry,
        session_manager: SessionManager,
        skill_loader: Any,  # SkillLoader
        prompt_builder: PromptBuilder,
        subagent_runner: SubagentRunner,
        memory_store: Any,  # MarkdownMemoryStore
        mcp_provider: Any = None,  # MCPProvider (A2: MCP 标准工具接口)
        hooks: HookRegistry | None = None,
        runtime_config: RuntimeConfig | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.tool_registry = tool_registry
        self.session_manager = session_manager
        self.skill_loader = skill_loader
        self.prompt_builder = prompt_builder
        self.subagent_runner = subagent_runner
        self.memory_store = memory_store
        self.mcp_provider = mcp_provider
        self.hooks = hooks or build_default_hooks()
        self.runtime_config = runtime_config or RuntimeConfig(
            max_iterations=25,
            max_tokens_per_turn=4096,
        )

    # 会话摘要最大保留条数
    _MAX_CONVERSATION_ENTRIES = 20

    def _auto_save_memory(
        self,
        *,
        tenant_id: str,
        user_id: str,
        message: str,
        answer: str,
    ) -> None:
        """
        对话结束后自动保存会话摘要到记忆 (OpenClaw Session Memory Hook 模式)。

        不做特定模式匹配，直接保存用户消息 + 回复摘要到 conversations.md。
        下次会话时 build_memory_prompt() 会将其注入 <memory> 标签，
        LLM 自然地从历史对话中获取用户偏好、上下文等信息。
        """
        if not self.memory_store:
            return

        try:
            from datetime import datetime

            # 保存用户消息 + 回复摘要
            user_summary = message[:200].replace("\n", " ").strip()
            answer_summary = (answer or "")[:200].replace("\n", " ").strip()
            ts = datetime.now().strftime("%Y-%m-%d %H:%M")
            entry = f"\n### {ts}\n- 用户: {user_summary}\n- 回复: {answer_summary}\n"

            self.memory_store.write_file(
                scope="user", filename="conversations.md",
                content=entry, mode="append",
                tenant_id=tenant_id, user_id=user_id,
            )

            # 超过条数限制时裁剪，保留最近的
            conv_content = self.memory_store.read_file(
                scope="user", filename="conversations.md",
                tenant_id=tenant_id, user_id=user_id,
            )
            sections = conv_content.split("\n### ")
            if len(sections) > self._MAX_CONVERSATION_ENTRIES:
                kept = sections[-self._MAX_CONVERSATION_ENTRIES:]
                trimmed = "### " + "\n### ".join(kept)
                self.memory_store.write_file(
                    scope="user", filename="conversations.md",
                    content=trimmed, mode="rewrite",
                    tenant_id=tenant_id, user_id=user_id,
                )
                logger.info(f"Trimmed conversations.md for user {user_id}")

        except Exception as e:
            logger.warning(f"Auto-save memory failed: {e}")

    async def chat(
        self,
        *,
        tenant_id: str = "default",
        user_id: str = "U001",
        session_id: str | None = None,
        message: str,
        business_type: str,
        skill_names: list[str] | None = None,
        event_bus: EventBus | None = None,
        materials: list[dict] | None = None,
    ) -> dict:
        """
        处理用户消息 — 单一入口。

        Args:
            tenant_id: 租户 ID
            user_id: 用户 ID (隔离)
            session_id: 可选, 续接会话
            message: 用户消息
            business_type: 业务类型 (reimbursement_create 等)
            skill_names: 要加载的 Skills
            event_bus: SSE 事件总线
            materials: 上传的材料列表

        Returns:
            {"session_id": str, "answer": str, "iterations": int, ...}
        """
        start_time = time.time()

        # ── 1. 设置 contextvars ──
        if event_bus:
            current_event_bus.set(event_bus)
        current_tenant_id.set(tenant_id)
        current_user_id.set(user_id)

        # 注入 SubagentRunner 到 contextvars
        from tools.builtin.subagent_tools import _subagent_runner
        _subagent_runner.set(self.subagent_runner)

        # 注入 SkillLoader 到 contextvars (供 skill 管理工具使用)
        if self.skill_loader:
            current_skill_loader.set(self.skill_loader)

        # 注入 FileService 到 contextvars (供文件工具使用)
        try:
            from dependencies import get_file_service
            current_file_service.set(get_file_service())
        except Exception:
            logger.debug("FileService injection skipped", exc_info=True)

        # 注入 BrowserService 到 contextvars (供浏览器工具使用)
        try:
            from dependencies import get_browser_service
            current_browser_service.set(get_browser_service())
        except Exception:
            logger.debug("BrowserService injection skipped", exc_info=True)

        # 注入 known_field_ids 到 contextvars (供 known_values_guard hook 使用)
        current_known_field_ids.set(set())  # 始终初始化，避免 LookupError

        # A8: 注入 MarkdownMemoryStore 到 ContextVar (供记忆工具使用)
        if self.memory_store:
            current_memory_store.set(self.memory_store)

        # A6: 注入 SandboxManager + DataLockRegistry 到 ContextVar
        try:
            from dependencies import get_sandbox_manager, get_data_lock_registry
            current_sandbox.set(get_sandbox_manager())
            current_data_lock.set(get_data_lock_registry())
        except Exception:
            logger.debug("Sandbox/DataLock injection skipped", exc_info=True)

        # A2: 注入 MCPProvider 到 ContextVar (供 MCP 工具使用)
        if self.mcp_provider:
            current_mcp_provider.set(self.mcp_provider)

        # A9: 注入 Scheduler 到 ContextVar (供 schedule_tools 使用)
        try:
            from dependencies import get_scheduler
            current_scheduler.set(get_scheduler())
        except Exception:
            logger.debug("Scheduler injection skipped", exc_info=True)

        # ── 2. 解析/创建会话 ──
        if session_id and self.session_manager.session_exists(tenant_id, user_id, session_id):
            logger.info(f"Resuming session: {session_id}")
        else:
            # 用用户首条消息生成会话标题
            title = (message[:60].strip() + "...") if len(message) > 60 else message.strip()
            session_id = self.session_manager.create_session(
                tenant_id, user_id, {"business_type": business_type, "title": title}
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
        history_messages = self.session_manager.load_messages(tenant_id, user_id, session_id)

        # ── 4. 加载 Skills (A7: 多源) ──
        skill_knowledge = ""

        if self.skill_loader:
            # A7: 加载租户级和用户级 Skill (追加到 registry)
            try:
                import os
                from skills.loader import SKILLS_DIR, TENANT_DIR, USER_DIR
                tenant_skill_dir = os.path.join(TENANT_DIR, tenant_id)
                user_skill_dir = os.path.join(USER_DIR, f"{tenant_id}_{user_id}")
                if os.path.isdir(tenant_skill_dir):
                    self.skill_loader.load_tenant_skills(tenant_skill_dir)
                if os.path.isdir(user_skill_dir):
                    self.skill_loader.load_user_skills(user_skill_dir)
            except Exception as e:
                logger.debug(f"Tenant/user skill loading skipped: {e}")

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

        # ── 5. 构建 Memory 上下文 (A8: Markdown 分层笔记) ──
        memory_context = ""
        if self.memory_store:
            try:
                memory_context = self.memory_store.build_memory_prompt(
                    tenant_id=tenant_id,
                    user_id=user_id,
                )
            except Exception as e:
                logger.warning(f"MarkdownMemoryStore error: {e}")

        # ── 6. 构建系统提示 ──
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
            memory_context=memory_context,
            user_id=user_id,
            session_id=session_id,
            tool_summaries=tool_summaries,
        )

        # ── 7. 构建用户消息 (A4-4i: 多模态支持) ──
        from config import settings
        text_summaries: list[str] = []
        image_blocks: list[dict] = []
        for m in (materials or []):
            if not isinstance(m, dict):
                continue
            mat_type = m.get("material_type", "text")
            filename = m.get("filename", "")
            content = m.get("content", "")

            if mat_type == "image" and content and settings.llm_supports_vision:
                # A4-4i: 大图自动压缩 (>1024px 缩放, 控制 token 消耗)
                from services.content_processor import process_image
                import base64 as b64mod
                try:
                    raw_bytes = b64mod.b64decode(content)
                    processed = process_image(raw_bytes, filename)
                    image_blocks.append({
                        "base64": processed.image_base64,
                        "media_type": processed.image_media_type or "image/png",
                    })
                except Exception:
                    # fallback: 原样使用
                    media_type = mimetypes.guess_type(filename)[0] or "image/png"
                    image_blocks.append({"base64": content, "media_type": media_type})
                text_summaries.append(f"[Image: {filename}]")
            else:
                text_summaries.append(f"[{filename}]\n{content[:2000]}")

        materials_summary = "\n\n".join(text_summaries)

        user_message = self.prompt_builder.build_user_message(
            message=message,
            materials_summary=materials_summary,
            image_blocks=image_blocks or None,
        )

        # ── 8. 创建 AgenticRuntime 并执行 ──
        runtime = AgenticRuntime(
            llm_client=self.llm_client,
            tool_registry=self.tool_registry,
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

        # ── 9. 持久化会话 ──
        self.session_manager.append_message(
            tenant_id, user_id, session_id,
            {"role": "user", "content": message, "ts": start_time},
        )
        self.session_manager.append_message(
            tenant_id, user_id, session_id,
            {"role": "assistant", "content": result.final_answer, "ts": time.time()},
        )

        # ── 9b. 自动保存记忆 (OpenClaw 模式: 不依赖 LLM 调用) ──
        self._auto_save_memory(
            tenant_id=tenant_id,
            user_id=user_id,
            message=message,
            answer=result.final_answer or "",
        )

        # 上下文压缩检查
        history = self.session_manager.load_messages(tenant_id, user_id, session_id)
        if len(history) > 20:
            try:
                await self.session_manager.compact(tenant_id, user_id, session_id, self.llm_client)
            except Exception as e:
                logger.warning(f"Session compaction failed: {e}")

        # ── 10. 发射 Agent 文字回复 ──
        if result.final_answer and event_bus:
            event_bus.emit("agent_message", {
                "content": result.final_answer,
            })

        # 发射 thinking 汇总 (如果有且前端开启了展示思考)
        if result.thinking and event_bus:
            event_bus.emit("thinking_complete", {
                "content": result.thinking,
            })

        # ── 11. 触发 agent_stop hook ──
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

        # ── 12. PlanTracker 收尾 + 持久化 ──
        tracker = current_plan_tracker.get(None)
        if tracker:
            if result.error:
                tracker.fail_current()
            else:
                tracker.complete_all()
            # 持久化 plan steps 到会话文件
            try:
                self.session_manager.save_plan_steps(
                    tenant_id, user_id, session_id, tracker.steps,
                )
            except Exception as e:
                logger.debug(f"Failed to persist plan steps: {e}", exc_info=True)

        # ── 12b. 持久化 timeline (thinking + text + tool_executed) ──
        if event_bus:
            try:
                # 从 EventBus history 提取 thinking + text_delta + tool_executed 事件
                timeline_entries = []
                # text_delta 是流式 chunk，按 iteration 累积为单条 text 条目
                _text_accum: dict[int, str] = {}  # iteration → accumulated text
                for evt in event_bus.history:
                    if evt.event_type == "thinking":
                        # 先 flush 之前迭代的 text_delta 累积
                        for it in sorted(_text_accum):
                            if _text_accum[it]:
                                timeline_entries.append({
                                    "type": "text",
                                    "content": _text_accum[it],
                                    "iteration": it,
                                    "ts": evt.timestamp,
                                })
                        _text_accum.clear()
                        timeline_entries.append({
                            "type": "thinking",
                            "content": evt.data.get("content", ""),
                            "iteration": evt.data.get("iteration", 0),
                            "ts": evt.timestamp,
                        })
                    elif evt.event_type == "text_delta":
                        it = evt.data.get("iteration", 0)
                        _text_accum[it] = _text_accum.get(it, "") + evt.data.get("content", "")
                    elif evt.event_type == "tool_executed":
                        # flush 当前迭代的 text_delta 到 timeline (text 在 tool 之前)
                        for it in sorted(_text_accum):
                            if _text_accum[it]:
                                timeline_entries.append({
                                    "type": "text",
                                    "content": _text_accum[it],
                                    "iteration": it,
                                    "ts": evt.timestamp,
                                })
                        _text_accum.clear()
                        timeline_entries.append({
                            "type": "tool",
                            "tool_name": evt.data.get("tool", ""),
                            "success": evt.data.get("success", True),
                            "blocked": evt.data.get("blocked", False),
                            "latency_ms": evt.data.get("latency_ms", 0),
                            "args_summary": evt.data.get("args_summary", {}),
                            "result_summary": evt.data.get("result_summary", ""),
                            "ts": evt.timestamp,
                        })
                # flush 剩余 text_delta (最终迭代的文本)
                for it in sorted(_text_accum):
                    if _text_accum[it]:
                        timeline_entries.append({
                            "type": "text",
                            "content": _text_accum[it],
                            "iteration": it,
                            "ts": evt.timestamp if event_bus.history else 0,
                        })
                if timeline_entries:
                    # 计算 turn_index: 当前 assistant 消息在 messages 中的位置
                    messages = self.session_manager.load_messages(
                        tenant_id, user_id, session_id,
                    )
                    assistant_count = sum(
                        1 for m in messages if m.get("role") == "assistant"
                    )
                    self.session_manager.save_timeline(
                        tenant_id, user_id, session_id,
                        timeline_entries, turn_index=assistant_count - 1,
                    )
            except Exception as e:
                logger.debug(f"Failed to persist timeline: {e}", exc_info=True)

        # ── 13. 发射完成事件 ──
        duration_ms = (time.time() - start_time) * 1000
        if event_bus:
            status = "failed" if result.error else "success"

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

        # ── 14. 记录用量 (A10) ──
        try:
            from dependencies import get_usage_service
            usage_svc = get_usage_service()
            tool_names_used = list({
                s.tool_name for s in result.steps
                if s.step_type == StepType.TOOL_CALL and s.tool_name
            })
            usage_svc.record_pipeline(
                tenant_id=tenant_id, user_id=user_id,
                session_id=session_id, business_type=business_type,
                prompt_tokens=result.token_usage.prompt_tokens,
                completion_tokens=result.token_usage.completion_tokens,
                total_tokens=result.token_usage.total_tokens,
                tool_call_count=result.tool_call_count,
                iterations=result.iterations,
                duration_ms=round(duration_ms, 1),
                status="failed" if result.error else "success",
                model=self.llm_client.config.model,
                tool_names=tool_names_used,
            )
        except Exception as e:
            logger.warning(f"Usage recording failed: {e}")

        return {
            "session_id": session_id,
            "answer": result.final_answer,
            "iterations": result.iterations,
            "tool_calls": result.tool_call_count,
            "duration_ms": round(duration_ms, 1),
            "max_iterations_reached": result.max_iterations_reached,
        }
