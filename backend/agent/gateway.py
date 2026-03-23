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

from core.context import RequestContext, current_request
from core.event_bus import EventBus
from core.llm_client import LLMGatewayClient
from core.runtime import AgenticRuntime, RuntimeConfig, RuntimeResult, StepType
from core.tool_protocol import ToolCallParser
from core.tool_registry import ToolRegistry
from core.tracing import get_tracer

from agent.hooks import HookRegistry, build_default_hooks
from agent.prompt import PromptBuilder
from agent.session import SessionManager
from agent.subagent import SubagentRunner

logger = logging.getLogger(__name__)

# 核心工具名: 始终注入 prompt，不延迟加载
CORE_TOOL_NAMES: frozenset[str] = frozenset({
    # calculator
    "numeric_compare", "sum_values", "calculate_ratio", "arithmetic", "date_diff",
    # skill
    "read_reference", "create_skill", "update_skill",
    # file
    "read_uploaded_file", "list_user_files", "analyze_file", "read_knowledge_file",
    # code
    "read_source_file", "write_source_file", "apply_patch", "run_command",
    # memory
    "save_memory", "recall_memory", "search_memory",
    # plan
    "propose_plan", "update_plan_step",
    # subagent
    "spawn_subagent", "spawn_subagents", "wait_subagent", "send_to_subagent",
    # interaction
    "request_user_input", "request_permissions",
    # tool_search (self)
    "tool_search",
})


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
        secret_redactor: Any | None = None,
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
        self.secret_redactor = secret_redactor
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

    @staticmethod
    def _summarize_timeline(timeline_entries: list[dict]) -> str:
        """把 timeline_entries 压缩为每行一条的摘要，上限 1500 字符。"""
        lines: list[str] = []
        for i, entry in enumerate(timeline_entries, 1):
            etype = entry.get("type", "")
            if etype == "tool":
                tool_name = entry.get("tool_name", "unknown")
                args = entry.get("args_summary", {})
                args_str = ", ".join(f'{k}="{v}"' for k, v in args.items()) if args else ""
                success = entry.get("success", True)
                blocked = entry.get("blocked", False)
                result = entry.get("result_summary", "")
                if blocked:
                    status = "被阻止"
                elif success:
                    status = f"成功: {result[:80]}" if result else "成功"
                else:
                    status = f"失败: {result[:80]}" if result else "失败"
                lines.append(f"[{i}] {tool_name}({args_str}) → {status}")
            elif etype == "thinking":
                content = entry.get("content", "")[:60]
                if content:
                    lines.append(f"[{i}] thinking: {content}...")
        summary = "\n".join(lines)
        if len(summary) > 1500:
            summary = summary[:1497] + "..."
        return summary

    # 类级标记: 每个进程只清理一次 thinking 垃圾
    _garbage_cleaned: set[str] = set()

    async def _auto_save_memory(
        self,
        *,
        tenant_id: str,
        user_id: str,
        message: str,
        answer: str,
        timeline_entries: list[dict] | None = None,
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

        # ── Step 6: 一次性清理 thinking 垃圾数据 ──
        cleanup_key = f"{tenant_id}/{user_id}"
        if cleanup_key not in self._garbage_cleaned:
            self._garbage_cleaned.add(cleanup_key)
            try:
                self._cleanup_thinking_garbage(tenant_id, user_id)
            except Exception as e:
                logger.debug(f"Thinking garbage cleanup failed (silent): {e}")

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
                "你是一个精确的记忆提取器。分析对话，提取值得跨会话保留的信息。\n\n"
                "## 第一步: No-op Gate (必须首先执行)\n"
                "逐项检查以下条件，任意满足则直接输出 NONE:\n"
                "1. 对话是闲聊/打招呼/感谢/通用问答 → NONE\n"
                "2. 对话内容是通用知识 (任何人都知道的事) → NONE\n"
                "3. 对话仅涉及临时性数据 (一次性文件名、临时数值、特定 session 的细节) → NONE\n"
                "4. 所有可能的提取项都已存在于 <existing_memory> 中 → NONE\n"
                "5. 未来 Agent 不会因为这条记忆而行为不同 → NONE\n"
                "大多数对话 (>80%) 不需要提取任何内容。宁可漏掉也不要提取垃圾。\n\n"
                "## 第二步: Task Outcome Triage\n"
                "判断本次任务结果:\n"
                "- 成功 → 只提取用户偏好/纠正/决策/角色 (不提取任务本身的具体内容)\n"
                "- 失败 → 额外提取失败教训 (防止重蹈覆辙): when <situation>, <what failed> because <why>\n"
                "- 部分成功 → 提取哪些有效、哪些无效\n\n"
                "## 第三步: 提取 (仅在通过 No-op Gate 且确有提取项时)\n"
                "### 类型\n"
                "- [偏好] 用户对输出格式/风格/方法的偏好\n"
                "  - 显式: 「我喜欢...」「请用...」「不要...」\n"
                "  - 隐式: 用户反复选择某方案、多次修改同一类输出\n"
                "- [纠正] 用户纠正了 Agent 行为，或某方法行不通的教训\n"
                "  - 格式: when <situation>, user said: '<原文引用>' -> <启示>\n"
                "- [决策] 重要的技术/业务选型 (架构、工具、流程)\n"
                "- [角色] 用户身份、职责、专业领域\n\n"
                "### Evidence-first 原则\n"
                "- 区分「用户明确说的」vs「Agent 推断的」\n"
                "- 优先引用用户原话作为依据\n"
                "- 不确定时不提取\n\n"
                "## 绝对禁止提取\n"
                "- 对话的具体内容摘要或总结\n"
                "- 临时任务细节 (文件名、具体数值、session ID)\n"
                "- 已在 <existing_memory> 中的信息\n"
                "- Agent 能力描述或通用知识\n"
                "- Agent 的思考过程、推理步骤\n\n"
                "## 输出格式 (严格)\n"
                "有提取项时，每条一行，格式必须为:\n"
                "- [偏好] 具体内容\n"
                "- [纠正] 具体内容\n"
                "- [决策] 具体内容\n"
                "- [角色] 具体内容\n"
                "无提取项时，只输出: NONE\n"
                "不要输出任何其他格式、解释或前言。\n\n"
                f"<existing_memory>\n{existing_memory[:2000]}\n</existing_memory>\n\n"
                f"<conversation>\n"
                f"用户: {message[:1000]}\n"
                f"Agent: {answer[:1000]}\n"
                + (
                    f"\n<timeline>\n{self._summarize_timeline(timeline_entries)}\n</timeline>\n"
                    if timeline_entries else ""
                )
                + f"</conversation>"
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

            # 脱敏: 移除可能泄露的 secret
            if self.secret_redactor:
                extracted = self.secret_redactor.redact(extracted)

            # 格式校验: 每行应以 "- [" 开头
            lines = [l.strip() for l in extracted.splitlines() if l.strip()]
            valid_lines = [l for l in lines if l.startswith("- [")]
            if not valid_lines:
                logger.info("Auto-extract: no valid memory lines, discarding")
                return
            extracted = "\n".join(valid_lines)

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

    def _cleanup_thinking_garbage(self, tenant_id: str, user_id: str) -> None:
        """
        清理 auto-learning.md 中的 thinking 垃圾数据。

        如果文件内容包含 thinking 特征字符串，说明是旧版未分离 thinking 时写入的垃圾，
        直接清空文件内容，让后续对话重新积累干净的记忆。
        """
        GARBAGE_MARKERS = ("Thinking Process:", "<think>", "</think>", "**Thinking")
        try:
            content = self.memory_store.read_file(
                scope="user",
                filename="auto-learning.md",
                tenant_id=tenant_id,
                user_id=user_id,
            )
            if not content:
                return
            if any(marker in content for marker in GARBAGE_MARKERS):
                logger.warning(
                    f"Detected thinking garbage in auto-learning.md for {tenant_id}/{user_id}, "
                    f"clearing {len(content)} chars"
                )
                self.memory_store.write_file(
                    scope="user",
                    filename="auto-learning.md",
                    content="# Auto Learning\n\n",
                    mode="rewrite",
                    tenant_id=tenant_id,
                    user_id=user_id,
                )
        except Exception:
            pass  # 文件不存在或读取失败，静默跳过

    def _setup_context_vars(
        self, *, tenant_id: str, user_id: str, event_bus: EventBus | None,
    ) -> RequestContext:
        """
        构建 RequestContext 并注入 ContextVar。

        返回 ctx 供 Gateway 方法直接传递，避免逐个参数透传。
        """
        # ── 收集依赖 ──
        file_service = None
        try:
            from dependencies import get_file_service
            file_service = get_file_service()
        except Exception:
            logger.debug("FileService injection skipped", exc_info=True)

        browser_service = None
        try:
            from dependencies import get_browser_service
            browser_service = get_browser_service()
        except Exception:
            logger.debug("BrowserService injection skipped", exc_info=True)

        sandbox = None
        data_lock = None
        try:
            from dependencies import get_sandbox_manager, get_data_lock_registry
            sandbox = get_sandbox_manager()
            data_lock = get_data_lock_registry()
        except Exception:
            logger.debug("Sandbox/DataLock injection skipped", exc_info=True)

        scheduler = None
        try:
            from dependencies import get_scheduler
            scheduler = get_scheduler()
        except Exception:
            logger.debug("Scheduler injection skipped", exc_info=True)

        # ── 构建 RequestContext ──
        ctx = RequestContext(
            tenant_id=tenant_id,
            user_id=user_id,
            event_bus=event_bus,
            skill_loader=self.skill_loader,
            file_service=file_service,
            browser_service=browser_service,
            memory_store=self.memory_store,
            sandbox=sandbox,
            data_lock=data_lock,
            mcp_provider=self.mcp_provider,
            scheduler=scheduler,
            subagent_runner=self.subagent_runner,
            known_field_ids=set(),
        )
        current_request.set(ctx)

        return ctx

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
        mode: str = "execute",
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
        ctx = self._setup_context_vars(
            tenant_id=tenant_id, user_id=user_id, event_bus=event_bus,
        )

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

        ctx.session_id = session_id

        # ── 2a. 绑定上传文件到会话 ──
        if materials:
            file_ids = [
                m.get("material_id", "").removeprefix("file-")
                for m in materials
                if m.get("material_id", "").startswith("file-")
            ]
            if file_ids and ctx.file_service:
                try:
                    bound = ctx.file_service.bind_files_to_session(
                        tenant_id, user_id, file_ids, session_id,
                    )
                    if bound:
                        logger.info(f"Bound {bound} files to session {session_id}")
                except Exception:
                    logger.debug("File binding skipped", exc_info=True)

        # ── 2b. 获取 session 级文件锁 (跨 worker 互斥) ──
        session_lock_fd = self._acquire_session_lock(tenant_id, user_id, session_id)

        try:  # session lock — finally 中释放
            return await self._chat_inner(
                ctx=ctx, message=message,
                business_type=business_type, skill_names=skill_names,
                materials=materials, start_time=start_time,
                mode=mode,
            )
        finally:
            try:
                fcntl.flock(session_lock_fd, fcntl.LOCK_UN)
                os.close(session_lock_fd)
            except OSError:
                pass

    def _load_prompt_sources(
        self, *, ctx: RequestContext, business_type: str,
    ) -> tuple[str, str, str]:
        """加载 Skill + Memory + 知识库索引，返回 (skill_knowledge, memory_context, knowledge_index_text)。"""
        tenant_id, user_id, session_id = ctx.tenant_id, ctx.user_id, ctx.session_id
        event_bus = ctx.event_bus

        # ── Skills (A7: 多源) ──
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
                skill_knowledge, loaded_skill_names = self.skill_loader.build_skill_index(
                    scenario=scenario,
                    agent_name="universal",
                    business_type=bt,
                )
                if loaded_skill_names and event_bus:
                    event_bus.emit("skills_loaded", {"skills": loaded_skill_names, "count": len(loaded_skill_names)})
                    try:
                        self.session_manager.save_loaded_skills(
                            tenant_id, user_id, session_id, loaded_skill_names,
                        )
                    except Exception:
                        pass
            except Exception as e:
                logger.warning(f"Skill loading failed: {e}")

        # ── Memory (A8: Markdown 分层笔记) ──
        memory_context = ""
        if self.memory_store:
            try:
                memory_context = self.memory_store.build_memory_prompt(
                    tenant_id=tenant_id,
                    user_id=user_id,
                )
            except Exception as e:
                logger.warning(f"MarkdownMemoryStore error: {e}")

        # ── 知识库索引 (_index.md) ──
        knowledge_index_text = ""
        try:
            from dependencies import get_knowledge_service
            kb_service = get_knowledge_service()
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

        return skill_knowledge, memory_context, knowledge_index_text

    def _build_prompt_and_message(
        self, *, ctx: RequestContext,
        message: str, materials: list[dict] | None,
        skill_knowledge: str, memory_context: str, knowledge_index_text: str,
        start_time: float, mode: str = "execute",
    ) -> tuple[str, str | list]:
        """构建 system prompt + user message，并持久化用户消息。返回 (system_prompt, user_message)。"""
        tenant_id, user_id, session_id = ctx.tenant_id, ctx.user_id, ctx.session_id

        # ── 系统提示 (2.3: 延迟工具加载) ──
        from agent.prompt import ToolSummary
        from config import settings as _cfg

        all_tools = self.tool_registry.list_tools()
        deferred_tool_count = 0

        if len(all_tools) > _cfg.agent_tool_deferred_threshold:
            # 延迟模式: prompt 只注入核心工具 + tool_search
            core_summaries = []
            deferred = []
            for t in all_tools:
                if t.name in CORE_TOOL_NAMES:
                    core_summaries.append(ToolSummary(
                        name=t.name, description=t.description, read_only=t.read_only,
                    ))
                else:
                    deferred.append(t)
            tool_summaries = core_summaries
            ctx.deferred_tools = deferred
            deferred_tool_count = len(deferred)
        else:
            tool_summaries = [
                ToolSummary(name=t.name, description=t.description, read_only=t.read_only)
                for t in all_tools
            ]

        # Plan 模式: 只保留只读工具 + plan 工具
        if mode == "plan":
            PLAN_MODE_EXTRA = {"propose_plan", "update_plan_step"}
            tool_summaries = [
                t for t in tool_summaries
                if t.read_only or t.name in PLAN_MODE_EXTRA
            ]

        system_prompt = self.prompt_builder.build_system_prompt(
            skill_knowledge=skill_knowledge,
            memory_context=memory_context,
            knowledge_index_text=knowledge_index_text,
            user_id=user_id,
            session_id=session_id,
            tool_summaries=tool_summaries,
            deferred_tool_count=deferred_tool_count,
            chat_mode=mode,
        )

        # ── 用户消息 (A4-4i: 多模态支持) ──
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

        # ── 提前持久化用户消息 (运行中即可被 API 查到) ──
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

        return system_prompt, user_message

    async def _persist_results(
        self, *, ctx: RequestContext,
        message: str, business_type: str,
        result: RuntimeResult | None, cancelled: bool, runtime_error: Exception | None,
        start_time: float,
    ) -> dict:
        """持久化结果 (消息/记忆/timeline/plan/用量/完成事件)。返回 response dict。"""
        tenant_id, user_id, session_id = ctx.tenant_id, ctx.user_id, ctx.session_id
        event_bus = ctx.event_bus

        # ── 持久化 assistant 回复 — 总是保存 ──
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

        # ── 构建 timeline entries (提前构建，供 memory 提取和持久化共用) ──
        timeline_entries: list[dict] = []
        if event_bus:
            try:
                _text_accum: dict[int, str] = {}
                for evt in event_bus.history:
                    if evt.event_type == "thinking":
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
                for it in sorted(_text_accum):
                    if _text_accum[it]:
                        timeline_entries.append({
                            "type": "text",
                            "content": _text_accum[it],
                            "iteration": it,
                            "ts": evt.timestamp if event_bus.history else 0,
                        })
            except Exception as e:
                logger.debug(f"Failed to build timeline: {e}", exc_info=True)

        # ── memory/compact/agent_message/thinking/hooks — 仅正常完成 ──
        if result and not cancelled and not runtime_error:
            await self._auto_save_memory(
                tenant_id=tenant_id,
                user_id=user_id,
                message=message,
                answer=result.final_answer or "",
                timeline_entries=timeline_entries or None,
            )

            # 上下文压缩检查
            history = self.session_manager.load_messages(tenant_id, user_id, session_id)
            if len(history) > 20:
                try:
                    await self.session_manager.compact(tenant_id, user_id, session_id, self.llm_client)
                except Exception as e:
                    logger.warning(f"Session compaction failed: {e}")

            # 发射 Agent 文字回复
            if result.final_answer and event_bus:
                event_bus.emit("agent_message", {
                    "content": result.final_answer,
                })

            # 发射 thinking 汇总
            if result.thinking and event_bus:
                event_bus.emit("thinking_complete", {
                    "content": result.thinking,
                })

            # 触发 agent_stop hook
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

        # ── PlanTracker 收尾 + 持久化 — 总是保存 ──
        tracker = ctx.plan_tracker
        if tracker:
            if runtime_error:
                tracker.fail_current()
            try:
                self.session_manager.save_plan_steps(
                    tenant_id, user_id, session_id, tracker.steps,
                )
            except Exception as e:
                logger.debug(f"Failed to persist plan steps: {e}", exc_info=True)

        # ── 持久化 timeline — 总是保存 ──
        if timeline_entries:
            try:
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

        # ── TurnDiffTracker: 生成 diff + 发射事件 + timeline ──
        if ctx.diff_tracker:
            file_changes = ctx.diff_tracker.generate_diffs()
            if file_changes and event_bus:
                event_bus.emit("file_changes", {"changes": file_changes})
            if file_changes:
                for fc in file_changes:
                    timeline_entries.append({
                        "type": "file_change",
                        "path": fc["path"],
                        "operation": fc["operation"],
                        "diff_text": fc["diff_text"][:2000],
                        "before_size": fc["before_size"],
                        "after_size": fc["after_size"],
                        "ts": time.time(),
                    })

        # ── 发射完成事件 — 总是发射 ──
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

        # ── 记录用量 (A10) — 仅正常完成 ──
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

    async def _chat_inner(
        self,
        *,
        ctx: RequestContext,
        message: str,
        business_type: str,
        skill_names: list[str] | None,
        materials: list[dict] | None,
        start_time: float,
        mode: str = "execute",
    ) -> dict:
        """chat() 的核心逻辑，已在 session lock 保护下执行。"""
        tenant_id, user_id, session_id = ctx.tenant_id, ctx.user_id, ctx.session_id
        event_bus = ctx.event_bus

        # ── 1. 发射 pipeline_started ──
        if event_bus:
            event_bus.emit("pipeline_started", {
                "session_id": session_id,
                "business_type": business_type,
            })

        # ── 2. 加载会话历史 + PlanTracker ──
        history_messages = self.session_manager.load_messages(tenant_id, user_id, session_id)

        saved_plan = self.session_manager.load_plan_steps(tenant_id, user_id, session_id)
        if saved_plan:
            from agent.plan_tracker import PlanTracker
            restored_tracker = PlanTracker.restore(saved_plan, event_bus=event_bus)
            ctx.plan_tracker = restored_tracker
            logger.info(f"Restored PlanTracker with {len(saved_plan)} steps for session {session_id}")

        # ── 2c. 创建 TurnDiffTracker ──
        if ctx.sandbox:
            from core.file_diff_tracker import TurnDiffTracker
            workspace = ctx.sandbox.get_workspace(ctx.tenant_id, ctx.user_id, ctx.session_id)
            ctx.diff_tracker = TurnDiffTracker(workspace=str(workspace))

        # ── 3. 加载 Skill + Memory + 知识库 ──
        skill_knowledge, memory_context, knowledge_index_text = self._load_prompt_sources(
            ctx=ctx, business_type=business_type,
        )

        # ── 4. 构建 Prompt + Message ──
        system_prompt, user_message = self._build_prompt_and_message(
            ctx=ctx, message=message, materials=materials,
            skill_knowledge=skill_knowledge, memory_context=memory_context,
            knowledge_index_text=knowledge_index_text, start_time=start_time,
            mode=mode,
        )

        # ── 5. 执行 Runtime (2.3: 延迟模式传 llm_tool_registry) ──
        llm_tool_registry = None
        if mode == "plan":
            plan_allowed = {t.name for t in self.tool_registry.list_tools() if t.read_only}
            plan_allowed |= {"propose_plan", "update_plan_step"}
            llm_tool_registry = self.tool_registry.subset(plan_allowed)
        elif ctx.deferred_tools:
            llm_tool_registry = self.tool_registry.subset(CORE_TOOL_NAMES)

        runtime = AgenticRuntime(
            llm_client=self.llm_client,
            tool_registry=self.tool_registry,
            tool_parser=ToolCallParser(),
            config=self.runtime_config,
            event_bus=event_bus,
            trace_id=event_bus.trace_id if event_bus else "",
            hooks=self.hooks,
            secret_redactor=self.secret_redactor,
            llm_tool_registry=llm_tool_registry,
        )

        initial_messages = history_messages if history_messages else None
        result: RuntimeResult | None = None
        cancelled = False
        runtime_error: Exception | None = None

        tracer = get_tracer()
        with tracer.start_as_current_span("gateway.chat") as span:
            span.set_attribute("session_id", session_id)
            span.set_attribute("tenant_id", tenant_id)

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

        # ── 6. 持久化 + 返回 ──
        return await self._persist_results(
            ctx=ctx, message=message, business_type=business_type,
            result=result, cancelled=cancelled, runtime_error=runtime_error,
            start_time=start_time,
        )
