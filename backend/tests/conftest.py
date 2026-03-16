"""Shared fixtures for backend tests."""
import asyncio
import os
import tempfile
from pathlib import Path

import pytest

# ── LLM 配置：统一从环境变量读取，只需改 .env ──

LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:39107/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "instruct_model")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "not-needed")


@pytest.fixture
def tmp_dir(tmp_path):
    """Provide a temp directory for test data."""
    return tmp_path


@pytest.fixture
def event_loop():
    """Create an event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
