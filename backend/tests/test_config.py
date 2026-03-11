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
    assert s.llm_model == "qwen2.5"


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
    s = Settings(_env_file=None)
    assert s.llm_model == "gpt-4"
    assert s.auth_enabled is True


def test_model_config_has_env_file():
    assert "env_file" in Settings.model_config
    assert Settings.model_config["env_file"] == ".env"
