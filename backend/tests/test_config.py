"""Tests for config.py — Settings."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import Settings


def test_default_llm_base_url():
    s = Settings(_env_file=None)
    assert s.llm_base_url == "http://localhost:11434/v1"


def test_default_llm_model():
    s = Settings(_env_file=None)
    assert s.llm_model == ""


def test_default_auth_enabled():
    s = Settings(_env_file=None)
    assert s.auth_enabled is False


def test_default_agent_max_iterations():
    s = Settings(_env_file=None)
    assert s.agent_max_iterations == 25


def test_default_log_level():
    s = Settings(_env_file=None)
    assert s.log_level == "INFO"


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "gpt-4")
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_JWT_SECRET", "test-secret-key")
    s = Settings(_env_file=None)
    assert s.llm_model == "gpt-4"
    assert s.auth_enabled is True


def test_model_config_has_env_file():
    assert "env_file" in Settings.model_config
    assert Settings.model_config["env_file"] == ".env"


# ── A2: model_validator — jwt_secret required ──

def test_jwt_secret_required_when_auth_enabled(monkeypatch):
    """auth_enabled=True + auth_mode='jwt' 但缺 jwt_secret 时应抛 ValueError。"""
    import pytest
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_MODE", "jwt")
    # 不设置 AUTH_JWT_SECRET
    monkeypatch.delenv("AUTH_JWT_SECRET", raising=False)
    with pytest.raises(Exception, match="auth_jwt_secret must be set"):
        Settings(_env_file=None)


def test_jwt_secret_accepted_when_provided(monkeypatch):
    """提供 jwt_secret 时不应报错。"""
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_MODE", "jwt")
    monkeypatch.setenv("AUTH_JWT_SECRET", "my-secret-key")
    s = Settings(_env_file=None)
    assert s.auth_jwt_secret == "my-secret-key"


def test_auth_disabled_no_jwt_secret_required(monkeypatch):
    """auth_enabled=False 时不需要 jwt_secret。"""
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.delenv("AUTH_JWT_SECRET", raising=False)
    s = Settings(_env_file=None)
    assert s.auth_enabled is False


# ── A3: CORS 配置 ──

def test_cors_allowed_origins_default():
    """默认 cors_allowed_origins 为 '*'。"""
    s = Settings(_env_file=None)
    assert s.cors_allowed_origins == "*"


def test_cors_allowed_origins_comma_parsing(monkeypatch):
    """逗号分隔的 origins 能被正确解析。"""
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "http://a.com, http://b.com")
    s = Settings(_env_file=None)
    origins = [o.strip() for o in s.cors_allowed_origins.split(",") if o.strip()]
    assert origins == ["http://a.com", "http://b.com"]


# ── A5: app_debug 默认值 ──

def test_app_debug_defaults_false():
    """app_debug 默认应为 False (而非 True)。"""
    s = Settings(_env_file=None)
    assert s.app_debug is False


# ── T-02: 边界值测试 ──

def test_negative_max_iterations(monkeypatch):
    """负数 max_iterations 应被接受（Pydantic 不限制）。"""
    monkeypatch.setenv("AGENT_MAX_ITERATIONS", "-1")
    s = Settings(_env_file=None)
    assert s.agent_max_iterations == -1


def test_zero_timeout(monkeypatch):
    """超时为 0 应被接受。"""
    monkeypatch.setenv("LLM_TIMEOUT_S", "0")
    s = Settings(_env_file=None)
    assert s.llm_timeout_s == 0.0


def test_empty_llm_base_url(monkeypatch):
    """空 LLM_BASE_URL 应被接受。"""
    monkeypatch.setenv("LLM_BASE_URL", "")
    s = Settings(_env_file=None)
    assert s.llm_base_url == ""


def test_large_context_window(monkeypatch):
    """超大 context window 值应被接受。"""
    monkeypatch.setenv("AGENT_MODEL_CONTEXT_WINDOW", "1000000")
    s = Settings(_env_file=None)
    assert s.agent_model_context_window == 1_000_000


def test_zero_max_iterations(monkeypatch):
    """0 迭代次数应被接受。"""
    monkeypatch.setenv("AGENT_MAX_ITERATIONS", "0")
    s = Settings(_env_file=None)
    assert s.agent_max_iterations == 0


def test_budget_ratio_boundaries(monkeypatch):
    """预算比例边界值 (0.0 和 1.0)。"""
    monkeypatch.setenv("AGENT_CONTEXT_BUDGET_RATIO", "0.0")
    s = Settings(_env_file=None)
    assert s.agent_context_budget_ratio == 0.0

    monkeypatch.setenv("AGENT_CONTEXT_BUDGET_RATIO", "1.0")
    s2 = Settings(_env_file=None)
    assert s2.agent_context_budget_ratio == 1.0


def test_invalid_type_raises(monkeypatch):
    """非数字值应抛出验证错误。"""
    import pytest
    monkeypatch.setenv("AGENT_MAX_ITERATIONS", "not_a_number")
    with pytest.raises(Exception):
        Settings(_env_file=None)
