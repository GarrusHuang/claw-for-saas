"""
Agent Gateway — 对标 OpenClaw Gateway / Claude Code Agent Loop。

A2 简化:
- 去掉 business_context 推送 (MCP 拉取模式)
- 去掉 plan_mode 双模式 (Plan 纯进度展示)
- 单一工具集，Agent 自主决策
"""

from __future__ import annotations

import asyncio
import fcntl
import logging
import os
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


class SessionBusyError(Exception):
    """当同一 session 已有正在处理的请求时抛出。"""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        super().__init__(f"Session {session_id} is busy (concurrent request rejected)")


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

    @staticmethod
    def _extract_partial_answer(event_bus: EventBus | None) -> str:
        """从 EventBus history 提取已流式输出的文本，拼成取消消息。"""
        if not event_bus:
            return "[任务被终止]"
        parts: list[str] = []
        for evt in event_bus.history:
            if evt.event_type == "text_delta":
                parts.append(evt.data.get("content", ""))
        streaming_text = "".join(parts).strip()
        if streaming_text:
            return f"[任务被终止]\n\n{streaming_text}"
        return "[任务被终止]"

    def _acquire_session_lock(
        self, tenant_id: str, user_id: str, session_id: str,
    ) -> int:
        """
        获取 session 级文件锁 (跨 worker 互斥)。

        使用 fcntl.flock(LOCK_EX | LOCK_NB) 非阻塞锁定 session 的 .lock 文件。
        返回 fd (调用方负责在请求结束时 close)。
        如果已被锁定, 抛出 SessionBusyError。
        """
        lock_dir = self.session_manager.base_dir / tenant_id / user_id
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_path = lock_dir / f"{session_id}.lock"
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except (OSError, BlockingIOError):
            os.close(fd)
            raise SessionBusyError(session_id)

    async def _auto_save_memory(
        self,
        *,
        tenant_id: str,
        user_id: str,
        message: str,
        answer: str,
    ) -> None:
        """
        对话结束后自动提取跨会话记忆 (对标 Codex Session Memory Hook Phase1)。

        提取范围:
        - 用户偏好 ("我喜欢...", "请用...格式")
        - 纠正反馈 ("不要...", "应该...")
        - 关键决策 ("我们决定用...", "最终选择...")
        - 角色信息 ("我是...", "我负责...")

        不提取:
        - 对话摘要 (session 级上下文)
        - 临时数据 (一次性任务细节)
        - 已在记忆中存在的内容

        错误静默 — 提取失败不影响主流程。
        """
        from config import settings
        if not settings.memory_auto_extract_enabled:
            return
        if not self.memory_store or not self.llm_client:
            return

        # Guard: 消息太短，不值得提取
        if len(message) < 20 and len(answer) < 50:
            return

        try:
            # 读取现有记忆 (用于去重)
            existing_memory = ""
            try:
                existing_memory = self.memory_store.build_memory_prompt(
                    tenant_id=tenant_id, user_id=user_id
                )
            except Exception:
                pass

            extract_prompt = (
                "分析以下对话，提取值得跨会话记住的信息。\n\n"
                "## No-op Gate (最重要)\n"
                "问自己: 「未来 Agent 是否真的会因为这条记忆而行为不同？」\n"
                "如果答案是否，不要提取。大多数对话不需要提取任何内容。\n\n"
                "## 提取类型\n"
                "### 1. 用户偏好 (显式 + 隐式)\n"
                "- 显式: 用户直接说「我喜欢...」「请用...格式」「不要...」\n"
                "- 隐式: 用户反复选择某种方案、多次修改同一类输出格式\n"
                "- 标记: `[偏好]`\n\n"
                "### 2. 纠正反馈 (Failure Shield)\n"
                "- 用户纠正了 Agent 的行为: 「不是这样的」「应该用...」\n"
                "- 某种方法行不通的教训: 「用 X 方法不行，因为...」\n"
                "- 标记: `[纠正]`\n\n"
                "### 3. 关键决策 (Decision Trigger)\n"
                "- 用户做出的重要技术/业务决策: 「我们决定用 SQLite」\n"
                "- 架构选型、工具选择、流程确定\n"
                "- 标记: `[决策]`\n\n"
                "### 4. 角色信息\n"
                "- 用户身份、职责、专业领域: 「我是前端开发」「我负责...」\n"
                "- 标记: `[角色]`\n\n"
                "## Task Outcome Triage\n"
                "- 任务成功 → 只提取偏好/纠正/决策 (不提取任务本身)\n"
                "- 任务失败 → 额外提取失败教训 (防止重蹈覆辙)\n"
                "- 部分成功 → 提取哪些有效、哪些无效\n\n"
                "## 绝对不提取\n"
                "- 对话的具体内容摘要\n"
                "- 临时的、一次性的任务细节 (文件名、具体数值)\n"
                "- 已经在 <existing_memory> 中存在的信息 (去重!)\n"
                "- Agent 的能力描述或通用知识\n\n"
                "## 输出格式\n"
                "如果有值得记忆的信息，每条一行:\n"
                "`- [类型] 具体内容`\n"
                "如果没有值得提取的内容，只输出 `NONE`。\n\n"
                f"<existing_memory>\n{existing_memory[:2000]}\n</existing_memory>\n\n"
                f"<conversation>\n"
                f"用户: {message[:1000]}\n"
                f"Agent: {answer[:1000]}\n"
                f"</conversation>"
            )

            llm_resp = await asyncio.wait_for(
                self.llm_client.chat_completion(
                    messages=[
                        {"role": "system", "content": "你是记忆提取助手。只提取跨会话有价值的信息。"},
                        {"role": "user", "content": extract_prompt},
                    ],
                    max_tokens=settings.memory_auto_extract_max_tokens,
                    temperature=0.3,
                ),
                timeout=15.0,
            )

            if not llm_resp.content or llm_resp.content.strip().upper() == "NONE":
                return

            extracted = llm_resp.content.strip()

            # 保存到 auto-learning.md (独立文件，不与 Agent 手动管理的文件冲突)
            import time as _time
            date_str = _time.strftime("%Y-%m-%d %H:%M")
            entry = f"\n## {date_str}\n{extracted}\n"
            self.memory_store.append_memory(
                scope="user",
                tenant_id=tenant_id,
                user_id=user_id,
                filename="auto-learning.md",
                content=entry,
            )
            logger.info(f"Auto-extracted memory for {tenant_id}/{user_id}: {len(extracted)} chars")

        except asyncio.TimeoutError:
            logger.debug("Auto memory extraction timed out")
        except Exception as e:
            logger.debug(f"Auto memory extraction failed (silent): {e}")

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

        # ── 2a. 绑定上传文件到会话 ──
        if materials:
            file_ids = [
                m.get("material_id", "").removeprefix("file-")
                for m in materials
                if m.get("material_id", "").startswith("file-")
            ]
            if file_ids:
                try:
                    from dependencies import get_file_service
                    fs = get_file_service()
                    bound = fs.bind_files_to_session(tenant_id, user_id, file_ids, session_id)
                    if bound:
                        logger.info(f"Bound {bound} files to session {session_id}")
                except Exception:
                    logger.debug("File binding skipped", exc_info=True)

        # ── 2b. 获取 session 级文件锁 (跨 worker 互斥) ──
        # 同一 session 同一时刻只允许一个请求，避免并发写入导致数据损坏。
        # 锁定失败抛出 SessionBusyError，由 API 层捕获返回 409。
        session_lock_fd = self._acquire_session_lock(tenant_id, user_id, session_id)

        try:  # session lock — finally 中释放
            return await self._chat_inner(
                tenant_id=tenant_id, user_id=user_id,
                session_id=session_id, message=message,
                business_type=business_type, skill_names=skill_names,
                event_bus=event_bus, materials=materials,
                start_time=start_time,
            )
        finally:
            try:
                fcntl.flock(session_lock_fd, fcntl.LOCK_UN)
                os.close(session_lock_fd)
            except OSError:
                pass

    async def _chat_inner(
        self,
        *,
        tenant_id: str,
        user_id: str,
        session_id: str,
        message: str,
        business_type: str,
        skill_names: list[str] | None,
        event_bus: EventBus | None,
        materials: list[dict] | None,
        start_time: float,
    ) -> dict:
        """chat() 的核心逻辑，已在 session lock 保护下执行。"""
        # 发射 session 事件
        if event_bus:
            event_bus.emit("pipeline_started", {
                "session_id": session_id,
                "business_type": business_type,
            })

        # ── 3. 加载会话历史 ──
        history_messages = self.session_manager.load_messages(tenant_id, user_id, session_id)

        # ── 3b. 恢复上一轮的 PlanTracker (跨请求续接) ──
        saved_plan = self.session_manager.load_plan_steps(tenant_id, user_id, session_id)
        if saved_plan:
            from agent.plan_tracker import PlanTracker
            restored_tracker = PlanTracker.restore(saved_plan, event_bus=event_bus)
            current_plan_tracker.set(restored_tracker)
            logger.info(f"Restored PlanTracker with {len(saved_plan)} steps for session {session_id}")

        # ── 4. 加载 Skills (A7: 多源) ──
        skill_knowledge = ""

        if self.skill_loader:
            # A7: 加载租户级和用户级 Skill (追加到 registry)
            try:
                import os
                from skills.loader import TENANT_DIR, USER_DIR
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
                skill_knowledge, loaded_skill_names = self.skill_loader.build_skill_index(
                    scenario=scenario,
                    agent_name="universal",
                    business_type=bt,
                )
                if loaded_skill_names and event_bus:
                    event_bus.emit("skills_loaded", {"skills": loaded_skill_names, "count": len(loaded_skill_names)})
                    # 立即持久化 (不等 pipeline 结束，F5 后也能从 API 恢复)
                    try:
                        self.session_manager.save_loaded_skills(
                            tenant_id, user_id, session_id, loaded_skill_names,
                        )
                    except Exception:
                        pass
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

        # ── 5b. 加载知识库索引 (_index.md，两阶段: 索引注入 prompt，按需通过工具读取全文) ──
        knowledge_index_text = ""
        try:
            from dependencies import get_knowledge_service
            kb_service = get_knowledge_service()
            # 读取 _index.md 文件（优先用户级，合并全局级）
            index_parts: list[str] = []
            for index_path in kb_service.get_index_paths(tenant_id, user_id):
                if index_path.exists():
                    try:
                        index_parts.append(index_path.read_text(encoding="utf-8"))
                    except Exception as e:
                        logger.warning(f"Failed to read KB index {index_path}: {e}")
            knowledge_index_text = "\n\n".join(index_parts)
        except Exception as e:
            logger.debug(f"Knowledge index loading skipped: {e}")

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
            knowledge_index_text=knowledge_index_text,
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

        # ── 7b. 提前持久化用户消息 (运行中即可被 API 查到) ──
        user_msg: dict = {"role": "user", "content": message, "ts": start_time}
        if materials:
            file_refs = []
            for m in (materials or []):
                if not isinstance(m, dict):
                    continue
                if m.get("material_type") == "file":
                    mid = m.get("material_id", "")
                    fid = mid.removeprefix("file-") if mid.startswith("file-") else mid
                    if fid:
                        file_refs.append({
                            "fileId": fid,
                            "filename": m.get("filename", ""),
                        })
            if file_refs:
                user_msg["files"] = file_refs
        self.session_manager.append_message(
            tenant_id, user_id, session_id, user_msg,
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

        result: RuntimeResult | None = None
        cancelled = False
        runtime_error: Exception | None = None

        try:
            result = await runtime.run(
                system_prompt=system_prompt,
                user_message=user_message,
                initial_messages=initial_messages,
            )
        except asyncio.CancelledError:
            cancelled = True
            logger.info(f"Pipeline cancelled for session {session_id}")
        except Exception as e:
            runtime_error = e
            logger.error(f"AgenticRuntime failed: {e}")
            if event_bus:
                event_bus.emit("error", {
                    "code": "RUNTIME_ERROR",
                    "message": str(e),
                    "recoverable": False,
                })

        # ── 以下所有 save 无论哪种终止都执行 ──

        # ── 9. 持久化 assistant 回复 — 总是保存 ──
        if cancelled:
            answer = self._extract_partial_answer(event_bus)
        elif runtime_error:
            answer = f"执行失败: {runtime_error}"
        else:
            answer = result.final_answer

        self.session_manager.append_message(
            tenant_id, user_id, session_id,
            {"role": "assistant", "content": answer, "ts": time.time()},
        )

        # ── 9b/10/10c/11: memory/compact/agent_message/thinking/hooks — 仅正常完成 ──
        if result and not cancelled and not runtime_error:
            # 9b. 自动保存记忆 (对标 Codex Session Memory Hook)
            await self._auto_save_memory(
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

            # 10. 发射 Agent 文字回复
            if result.final_answer and event_bus:
                event_bus.emit("agent_message", {
                    "content": result.final_answer,
                })

            # 发射 thinking 汇总 (如果有且前端开启了展示思考)
            if result.thinking and event_bus:
                event_bus.emit("thinking_complete", {
                    "content": result.thinking,
                })

            # 11. 触发 agent_stop hook
            if self.hooks:
                from agent.hooks import HookEvent
                stop_event = HookEvent(
                    event_type="agent_completed",
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

        # ── 12. PlanTracker 收尾 + 持久化 — 总是保存 ──
        tracker = current_plan_tracker.get(None)
        if tracker:
            if runtime_error:
                tracker.fail_current()
            # cancelled/success: 不改步骤状态 (auto-complete 在执行期间已处理)
            # 持久化 plan steps 到会话文件
            try:
                self.session_manager.save_plan_steps(
                    tenant_id, user_id, session_id, tracker.steps,
                )
            except Exception as e:
                logger.debug(f"Failed to persist plan steps: {e}", exc_info=True)

        # ── 12b. 持久化 timeline — 总是保存 (从 bus.history 提取，不依赖 result) ──
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

        # ── 13. 发射完成事件 — 总是发射 ──
        duration_ms = (time.time() - start_time) * 1000
        if event_bus:
            if cancelled:
                status = "cancelled"
            elif runtime_error or (result and result.error):
                status = "failed"
            else:
                status = "success"

            summary: dict[str, Any] = {"session_id": session_id}
            if result:
                summary.update({
                    "iterations": result.iterations,
                    "tool_calls": result.tool_call_count,
                    "max_iterations_reached": result.max_iterations_reached,
                })

            event_bus.emit("pipeline_complete", {
                "status": status,
                "duration_ms": round(duration_ms, 1),
                "summary": summary,
            })

        # ── 14. 记录用量 (A10) — 仅正常完成 ──
        if result and not cancelled and not runtime_error:
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
            "answer": answer,
            "iterations": result.iterations if result else 0,
            "tool_calls": result.tool_call_count if result else 0,
            "duration_ms": round(duration_ms, 1),
            "max_iterations_reached": result.max_iterations_reached if result else False,
            **({"error": str(runtime_error)} if runtime_error else {}),
        }
