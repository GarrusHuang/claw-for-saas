"""Tests for LLM fallback mechanism in llm_client.py."""
import os
import sys
from unittest.mock import AsyncMock, patch

import httpx
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.llm_client import LLMGatewayClient, LLMClientConfig, LLMClientError


def _make_config(**overrides) -> LLMClientConfig:
    defaults = dict(
        base_url="http://primary:11434/v1",
        model="primary-model",
        api_key="test-key",
        max_retries=0,
        timeout_s=5.0,
    )
    defaults.update(overrides)
    return LLMClientConfig(**defaults)


def _make_fallback_config(**overrides) -> LLMClientConfig:
    defaults = dict(
        base_url="http://fallback:11434/v1",
        model="fallback-model",
        api_key="test-key",
        max_retries=0,
        timeout_s=5.0,
    )
    defaults.update(overrides)
    return LLMClientConfig(**defaults)


def _ok_response(model: str = "test") -> dict:
    return {
        "choices": [
            {"message": {"content": "ok"}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        "model": model,
    }


def _make_mock_client(post_fn):
    """Create a mock httpx.AsyncClient with a given post function."""
    mock = AsyncMock()
    mock.is_closed = False
    mock.post = post_fn
    return mock


class TestLLMFallback:
    @pytest.mark.asyncio
    async def test_no_fallback_raises_original_error(self):
        """Without fallback config, original error is raised."""
        client = LLMGatewayClient(config=_make_config())

        async def mock_post(url, **kwargs):
            return httpx.Response(503, text="Service Unavailable", request=httpx.Request("POST", url))

        client._client = _make_mock_client(mock_post)

        with pytest.raises(LLMClientError, match="503"):
            await client.chat_completion(messages=[{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_fallback_on_503(self):
        """Primary 503 → fallback succeeds, model contains '(fallback)'."""
        call_urls = []

        async def mock_post(url, **kwargs):
            call_urls.append(url)
            if "primary" in url:
                return httpx.Response(503, text="Overloaded", request=httpx.Request("POST", url))
            return httpx.Response(200, json=_ok_response("fallback-model"),
                                  request=httpx.Request("POST", url))

        client = LLMGatewayClient(
            config=_make_config(),
            fallback_config=_make_fallback_config(),
        )
        client._client = _make_mock_client(mock_post)

        result = await client.chat_completion(messages=[{"role": "user", "content": "hi"}])

        assert "fallback" in result.model
        assert result.content == "ok"
        assert len(call_urls) == 2  # primary + fallback

    @pytest.mark.asyncio
    async def test_fallback_on_model_unavailable(self):
        """500 with 'model not found' message triggers fallback."""
        async def mock_post(url, **kwargs):
            if "primary" in url:
                return httpx.Response(
                    500, text="model not found: primary-model",
                    request=httpx.Request("POST", url),
                )
            return httpx.Response(200, json=_ok_response("fallback-model"),
                                  request=httpx.Request("POST", url))

        client = LLMGatewayClient(
            config=_make_config(),
            fallback_config=_make_fallback_config(),
        )
        client._client = _make_mock_client(mock_post)

        result = await client.chat_completion(messages=[{"role": "user", "content": "hi"}])
        assert "fallback" in result.model

    @pytest.mark.asyncio
    async def test_no_fallback_on_auth_error(self):
        """401 errors should NOT trigger fallback — non-recoverable."""
        async def mock_post(url, **kwargs):
            return httpx.Response(401, text="Unauthorized",
                                  request=httpx.Request("POST", url))

        client = LLMGatewayClient(
            config=_make_config(),
            fallback_config=_make_fallback_config(),
        )
        client._client = _make_mock_client(mock_post)

        with pytest.raises(LLMClientError, match="401"):
            await client.chat_completion(messages=[{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_both_fail_raises_original(self):
        """Both primary and fallback fail → raises original error."""
        async def mock_post(url, **kwargs):
            return httpx.Response(503, text="Service Unavailable",
                                  request=httpx.Request("POST", url))

        client = LLMGatewayClient(
            config=_make_config(),
            fallback_config=_make_fallback_config(),
        )
        client._client = _make_mock_client(mock_post)

        with pytest.raises(LLMClientError, match="503"):
            await client.chat_completion(messages=[{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_primary_success_no_fallback(self):
        """Primary succeeds → fallback is never tried."""
        call_urls = []

        async def mock_post(url, **kwargs):
            call_urls.append(url)
            return httpx.Response(200, json=_ok_response("primary-model"),
                                  request=httpx.Request("POST", url))

        client = LLMGatewayClient(
            config=_make_config(),
            fallback_config=_make_fallback_config(),
        )
        client._client = _make_mock_client(mock_post)

        result = await client.chat_completion(messages=[{"role": "user", "content": "hi"}])

        assert result.model == "primary-model"
        assert "fallback" not in result.model
        assert len(call_urls) == 1


class TestDependenciesFallbackConfig:
    def test_fallback_config_built_when_model_set(self, monkeypatch):
        """dependencies.get_llm_client builds fallback_config when llm_fallback_model is set."""
        monkeypatch.setenv("LLM_MODEL", "main-model")
        monkeypatch.setenv("LLM_FALLBACK_MODEL", "backup-model")
        monkeypatch.setenv("LLM_FALLBACK_BASE_URL", "http://backup:11434/v1")

        from dependencies import get_llm_client, get_settings
        get_settings.cache_clear()
        get_llm_client.cache_clear()

        try:
            client = get_llm_client()
            assert client._fallback_config is not None
            assert client._fallback_config.model == "backup-model"
            assert client._fallback_config.base_url == "http://backup:11434/v1"
            assert client._fallback_config.max_retries == 0
        finally:
            get_settings.cache_clear()
            get_llm_client.cache_clear()

    def test_no_fallback_when_model_empty(self, monkeypatch):
        """No fallback_config when llm_fallback_model is empty."""
        monkeypatch.setenv("LLM_MODEL", "main-model")
        monkeypatch.setenv("LLM_FALLBACK_MODEL", "")

        from dependencies import get_llm_client, get_settings
        get_settings.cache_clear()
        get_llm_client.cache_clear()

        try:
            client = get_llm_client()
            assert client._fallback_config is None
        finally:
            get_settings.cache_clear()
            get_llm_client.cache_clear()
