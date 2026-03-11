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
    )
    client = LLMGatewayClient(config)
    _llm_client_instance = client
    return client


@lru_cache()
def get_shared_registry() -> ToolRegistry:
    return build_shared_registry()


@lru_cache()
def get_skill_loader() -> SkillLoader:
    return SkillLoader()


@lru_cache()
def get_runtime_config() -> RuntimeConfig:
    s = get_settings()
    return RuntimeConfig(
        max_iterations=s.agent_max_iterations,
        max_tokens_per_turn=s.llm_default_max_tokens,
        max_tool_result_chars=s.agent_max_tool_result_chars,
        context_budget_tokens=s.agent_context_budget_tokens,
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


# LLM client reference (for lifespan shutdown)
_llm_client_instance: LLMGatewayClient | None = None

# BrowserService singleton
_browser_service = None

def get_browser_service():
    global _browser_service
    if _browser_service is None:
        from services.browser_service import BrowserService
        _browser_service = BrowserService()
    return _browser_service


@lru_cache()
def get_hook_rule_engine():
    from agent.hook_rules import HookRuleEngine
    return HookRuleEngine(os.path.join(_BACKEND_ROOT, "data", "hook_rules"))


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
    plugin_tool_registry = ToolRegistry()
    ctx = PluginContext(
        tool_registry=plugin_tool_registry,
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

    tool_registry = build_full_registry()

    if plugin_tools and len(plugin_tools) > 0:
        tool_registry = tool_registry.merge(plugin_tools)

    session_manager = get_session_manager()

    subagent_runner = SubagentRunner(
        llm_client=llm_client,
        shared_registry=shared_registry,
        capability_registry=capability_registry,
        prompt_builder=prompt_builder,
    )

    return AgentGateway(
        llm_client=llm_client,
        tool_registry=tool_registry,
        session_manager=session_manager,
        skill_loader=get_skill_loader(),
        prompt_builder=prompt_builder,
        subagent_runner=subagent_runner,
        memory_store=get_memory_store(),
        hooks=build_default_hooks(),
        runtime_config=get_runtime_config(),
    )
