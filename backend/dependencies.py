"""
FastAPI dependency injection — component assembly center.

Builds the AgentGateway with all built-in tools.
SaaS integrators can extend by providing custom tool registries.
"""
from __future__ import annotations

import logging
import os
from functools import lru_cache
from config import Settings
from core.llm_client import LLMGatewayClient, LLMClientConfig
from core.runtime import RuntimeConfig
from core.tool_registry import ToolRegistry
from memory.markdown_store import MarkdownMemoryStore
from skills.loader import SkillLoader
from tools.registry_builder import (
    build_shared_registry,
    build_full_registry,
    build_capability_registry,
    build_mcp_registry,
)

logger = logging.getLogger(__name__)

_BACKEND_ROOT = os.path.dirname(os.path.abspath(__file__))


@lru_cache()
def get_settings() -> Settings:
    return Settings()


@lru_cache()
def get_llm_client() -> LLMGatewayClient:
    global _llm_client_instance
    s = get_settings()
    config = LLMClientConfig(
        base_url=s.llm_base_url,
        model=s.llm_model,
        api_key=s.llm_api_key,
        timeout_s=s.llm_timeout_s,
        max_retries=s.llm_max_retries,
        default_temperature=s.llm_default_temperature,
        default_top_p=s.llm_default_top_p,
        enable_thinking=s.llm_enable_thinking,
    )
    fallback_config = None
    if s.llm_fallback_model:
        fallback_config = LLMClientConfig(
            base_url=s.llm_fallback_base_url or s.llm_base_url,
            model=s.llm_fallback_model,
            api_key=s.llm_fallback_api_key or s.llm_api_key,
            timeout_s=s.llm_timeout_s,
            max_retries=0,  # 只试一次
            default_temperature=s.llm_default_temperature,
            default_top_p=s.llm_default_top_p,
            enable_thinking=s.llm_enable_thinking,
        )
        logger.info(f"LLM fallback configured: {s.llm_fallback_model}")

    client = LLMGatewayClient(config, fallback_config=fallback_config)
    _llm_client_instance = client
    return client


@lru_cache()
def get_shared_registry() -> ToolRegistry:
    return build_shared_registry()


@lru_cache()
def get_skill_loader() -> SkillLoader:
    s = get_settings()
    return SkillLoader(
        max_prompt_chars=s.skill_max_prompt_chars,
        max_single_chars=s.skill_max_single_chars,
    )


@lru_cache()
def get_sandbox_manager():
    from core.sandbox import SandboxManager, SandboxConfig
    s = get_settings()
    whitelist = [w.strip() for w in s.sandbox_network_whitelist.split(",") if w.strip()] if s.sandbox_network_whitelist else []
    config = SandboxConfig(
        workspace_base_dir=s.sandbox_workspace_dir,
        max_disk_quota_mb=s.sandbox_max_disk_quota_mb,
        network_whitelist=whitelist,
        block_private_networks=s.sandbox_block_private_networks,
        rate_limit_per_minute=s.sandbox_rate_limit_per_minute,
        docker_enabled=s.sandbox_docker_enabled,
        docker_image=s.sandbox_docker_image,
        docker_cpu_limit=s.sandbox_docker_cpu_limit,
        docker_memory_limit=s.sandbox_docker_memory_limit,
    )
    return SandboxManager(config=config, backend_root=_BACKEND_ROOT)


@lru_cache()
def get_data_lock_registry():
    from core.data_lock import DataLockRegistry
    return DataLockRegistry()


@lru_cache()
def get_runtime_config() -> RuntimeConfig:
    s = get_settings()
    return RuntimeConfig(
        max_iterations=s.agent_max_iterations,
        max_tokens_per_turn=s.llm_default_max_tokens,
        max_tool_result_chars=s.agent_max_tool_result_chars,
        tool_call_timeout_s=s.agent_tool_timeout_s,
        parallel_tool_calls=s.agent_parallel_tool_calls,
        context_budget_tokens=s.agent_context_budget_tokens,
        model_context_window=s.agent_model_context_window,
        context_budget_ratio=s.agent_context_budget_ratio,
        compress_threshold_ratio=s.agent_compress_threshold_ratio,
        context_budget_min=s.agent_context_budget_min,
    )


@lru_cache()
def get_memory_store() -> MarkdownMemoryStore:
    s = get_settings()
    base_dir = os.path.join(_BACKEND_ROOT, s.memory_storage_dir)
    return MarkdownMemoryStore(
        base_dir=base_dir,
        max_prompt_chars=s.memory_max_prompt_chars,
    )


@lru_cache()
def get_database():
    from services.database import DatabaseService
    s = get_settings()
    db_path = os.path.join(_BACKEND_ROOT, s.db_path)
    db = DatabaseService(db_path=db_path)
    db.ensure_default_tenant_and_admin(
        tenant_id=s.auth_default_tenant_id,
        admin_user_id=s.auth_default_user_id,
    )
    return db


@lru_cache()
def get_session_manager():
    from agent.session import SessionManager
    session_dir = os.path.join(_BACKEND_ROOT, "data", "sessions")
    return SessionManager(base_dir=session_dir)


@lru_cache()
def get_file_service():
    from services.file_service import FileService
    files_dir = os.path.join(_BACKEND_ROOT, "data", "files")
    return FileService(base_dir=files_dir)


@lru_cache()
def get_knowledge_service():
    from services.knowledge_service import KnowledgeService
    return KnowledgeService()


# LLM client reference (for lifespan shutdown)
_llm_client_instance: LLMGatewayClient | None = None

# BrowserService singleton
_browser_service = None

def get_browser_service():
    global _browser_service
    if _browser_service is None:
        from services.browser_service import BrowserService
        _browser_service = BrowserService()
        if not _browser_service.is_available():
            logger.warning(
                "Playwright browser not available — browser tools (open_url, page_screenshot, "
                "page_extract_text) will return errors. Run 'playwright install chromium' to fix."
            )
    return _browser_service


@lru_cache()
def get_schedule_store():
    from core.scheduler import ScheduleStore
    s = get_settings()
    base_dir = os.path.join(_BACKEND_ROOT, s.scheduler_data_dir)
    return ScheduleStore(base_dir=base_dir)


@lru_cache()
def get_webhook_store():
    from core.webhook import WebhookStore
    s = get_settings()
    base_dir = os.path.join(_BACKEND_ROOT, s.webhook_data_dir)
    return WebhookStore(base_dir=base_dir)


@lru_cache()
def get_webhook_dispatcher():
    from core.webhook import WebhookDispatcher
    s = get_settings()
    return WebhookDispatcher(
        store=get_webhook_store(),
        timeout_s=s.webhook_timeout_s,
        max_retries=s.webhook_max_retries,
    )


@lru_cache()
def get_scheduler():
    from core.scheduler import Scheduler
    s = get_settings()
    return Scheduler(
        store=get_schedule_store(),
        gateway_factory=build_gateway,
        webhook_dispatcher=get_webhook_dispatcher(),
        notification_manager=get_notification_manager(),
        check_interval_s=s.scheduler_check_interval_s,
    )


@lru_cache()
def get_notification_manager():
    from core.notification import NotificationManager
    return NotificationManager()


@lru_cache()
def get_secret_redactor():
    from core.secret_redactor import SecretRedactor
    redactor = SecretRedactor()
    redactor.collect_from_settings(get_settings())
    return redactor


@lru_cache()
def get_hook_rule_engine():
    from agent.hook_rules import HookRuleEngine
    return HookRuleEngine(os.path.join(_BACKEND_ROOT, "data", "hook_rules"))


@lru_cache()
def get_usage_service():
    from services.usage_service import UsageService
    s = get_settings()
    db_path = os.path.join(_BACKEND_ROOT, s.db_path)
    return UsageService(db_path=db_path)


@lru_cache()
def get_prompt_builder():
    from agent.prompt import PromptBuilder
    return PromptBuilder()


@lru_cache()
def get_plugin_registry():
    """PluginRegistry 单例 — 启动时加载插件。"""
    from core.plugin import PluginRegistry, PluginContext

    registry = PluginRegistry()
    s = get_settings()

    # 构建插件上下文 (四维扩展点)
    from agent.hooks import build_default_hooks as _build_plugin_hooks
    plugin_tool_registry = ToolRegistry()
    ctx = PluginContext(
        tool_registry=plugin_tool_registry,
        hook_registry=_build_plugin_hooks(),
        prompt_builder=get_prompt_builder(),
        skill_loader=get_skill_loader(),
    )

    # 从目录加载
    plugins_dir = os.path.join(_BACKEND_ROOT, s.plugins_dir)
    dir_count = registry.load_from_directory(plugins_dir, ctx)

    # 从 entry_points 加载
    ep_count = registry.load_from_entry_points("claw.plugins", ctx)

    if dir_count or ep_count:
        logger.info(f"Plugins loaded: {dir_count} from directory, {ep_count} from entry_points")

    # 保存插件工具注册表供 build_gateway merge
    registry._plugin_tool_registry = plugin_tool_registry  # type: ignore[attr-defined]

    return registry


def get_mcp_provider():
    """
    Get MCP Provider based on config.

    Returns HttpMCPProvider if mcp_base_url is set,
    otherwise None (tools will fallback to DefaultMCPProvider).
    """
    s = get_settings()
    if not s.mcp_enabled:
        return None
    if s.mcp_base_url:
        from tools.mcp.http_provider import HttpMCPProvider
        return HttpMCPProvider(
            base_url=s.mcp_base_url,
            timeout_s=s.mcp_timeout_s,
        )
    return None


def build_gateway():
    """
    Build Agent Gateway.

    Creates a new Gateway instance per request (EventBus is request-scoped).
    """
    from agent.gateway import AgentGateway
    from agent.subagent import SubagentRunner
    from agent.hooks import build_default_hooks

    llm_client = get_llm_client()
    shared_registry = get_shared_registry()
    capability_registry = build_capability_registry()
    prompt_builder = get_prompt_builder()

    # 合并插件工具到统一 registry
    plugin_registry = get_plugin_registry()
    plugin_tools: ToolRegistry | None = getattr(plugin_registry, "_plugin_tool_registry", None)

    s = get_settings()
    tool_registry = build_full_registry(mcp_enabled=s.mcp_enabled)

    if plugin_tools and len(plugin_tools) > 0:
        tool_registry = tool_registry.merge(plugin_tools)

    session_manager = get_session_manager()

    hooks = build_default_hooks()

    secret_redactor = get_secret_redactor()

    subagent_runner = SubagentRunner(
        llm_client=llm_client,
        shared_registry=shared_registry,
        capability_registry=capability_registry,
        prompt_builder=prompt_builder,
        hooks=hooks,
        secret_redactor=secret_redactor,
    )

    return AgentGateway(
        llm_client=llm_client,
        tool_registry=tool_registry,
        session_manager=session_manager,
        skill_loader=get_skill_loader(),
        prompt_builder=prompt_builder,
        subagent_runner=subagent_runner,
        memory_store=get_memory_store(),
        mcp_provider=get_mcp_provider(),
        hooks=hooks,
        runtime_config=get_runtime_config(),
        secret_redactor=secret_redactor,
    )
