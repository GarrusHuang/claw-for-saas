"""
Tests for dependencies.py — DI assembly center.

Does NOT use real LLM. Tests that DI functions return correct types.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest


@pytest.fixture(autouse=True)
def _clear_caches(tmp_path, monkeypatch):
    """Clear all lru_caches and redirect data dirs to tmp_path."""
    import dependencies

    # Set env vars to use tmp dirs
    monkeypatch.setenv("MEMORY_STORAGE_DIR", str(tmp_path / "memory"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("SKILLS_DIR", str(tmp_path / "skills"))
    monkeypatch.setenv("PLUGINS_DIR", str(tmp_path / "plugins"))

    # Clear all caches
    for name in dir(dependencies):
        obj = getattr(dependencies, name)
        if hasattr(obj, "cache_clear"):
            obj.cache_clear()

    yield

    # Clear again after
    for name in dir(dependencies):
        obj = getattr(dependencies, name)
        if hasattr(obj, "cache_clear"):
            obj.cache_clear()


def test_get_settings():
    """get_settings returns a Settings instance."""
    from dependencies import get_settings
    from config import Settings

    result = get_settings()
    assert isinstance(result, Settings)


def test_get_llm_client():
    """get_llm_client returns a LLMGatewayClient instance."""
    from dependencies import get_llm_client
    from core.llm_client import LLMGatewayClient

    result = get_llm_client()
    assert isinstance(result, LLMGatewayClient)


def test_get_shared_registry():
    """get_shared_registry returns a ToolRegistry with 6 tools."""
    from dependencies import get_shared_registry
    from core.tool_registry import ToolRegistry

    result = get_shared_registry()
    assert isinstance(result, ToolRegistry)
    assert len(result) == 6


def test_get_skill_loader():
    """get_skill_loader returns a SkillLoader instance."""
    from dependencies import get_skill_loader
    from skills.loader import SkillLoader

    result = get_skill_loader()
    assert isinstance(result, SkillLoader)


def test_get_runtime_config():
    """get_runtime_config returns a RuntimeConfig instance."""
    from dependencies import get_runtime_config
    from core.runtime import RuntimeConfig

    result = get_runtime_config()
    assert isinstance(result, RuntimeConfig)


def test_get_memory_store():
    """get_memory_store returns a MarkdownMemoryStore instance."""
    from dependencies import get_memory_store
    from memory.markdown_store import MarkdownMemoryStore

    result = get_memory_store()
    assert isinstance(result, MarkdownMemoryStore)


def test_get_session_manager():
    """get_session_manager returns a SessionManager instance."""
    from dependencies import get_session_manager
    from agent.session import SessionManager

    result = get_session_manager()
    assert isinstance(result, SessionManager)


def test_get_prompt_builder():
    """get_prompt_builder returns a PromptBuilder instance."""
    from dependencies import get_prompt_builder
    from agent.prompt import PromptBuilder

    result = get_prompt_builder()
    assert isinstance(result, PromptBuilder)


def test_build_gateway():
    """build_gateway returns an AgentGateway with all components."""
    from dependencies import build_gateway
    from agent.gateway import AgentGateway

    result = build_gateway()
    assert isinstance(result, AgentGateway)
    # Verify it has essential attributes
    assert hasattr(result, "llm_client")
    assert hasattr(result, "tool_registry")
    assert hasattr(result, "session_manager")
    assert hasattr(result, "prompt_builder")
    assert hasattr(result, "memory_store")


def test_get_database():
    """get_database returns a DatabaseService instance."""
    from dependencies import get_database
    from services.database import DatabaseService

    result = get_database()
    assert isinstance(result, DatabaseService)
