"""Tests for core/llm_client.py — LLM gateway client (integration + unit)."""
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.llm_client import LLMGatewayClient, LLMClientConfig, LLMResponse, TokenUsage, LLMClientError


# ── Unit tests (no LLM needed) ──


class TestLLMClientConfig:
    def test_defaults(self):
        cfg = LLMClientConfig()
        assert cfg.base_url == "http://localhost:11434/v1"
        assert cfg.max_retries == 3
        assert cfg.default_temperature == 0.7

    def test_custom(self):
        cfg = LLMClientConfig(base_url="http://example.com/v1", model="gpt-4")
        assert cfg.model == "gpt-4"


class TestTokenUsage:
    def test_defaults(self):
        u = TokenUsage()
        assert u.total_tokens == 0

    def test_values(self):
        u = TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150)
        assert u.total_tokens == 150


class TestLLMResponse:
    def test_defaults(self):
        r = LLMResponse()
        assert r.content is None
        assert r.tool_calls is None

    def test_to_message_dict_content(self):
        r = LLMResponse(content="Hello")
        msg = r.to_message_dict()
        assert msg["role"] == "assistant"
        assert msg["content"] == "Hello"
        assert "tool_calls" not in msg

    def test_to_message_dict_tool_calls(self):
        calls = [{"id": "c1", "function": {"name": "test", "arguments": "{}"}}]
        r = LLMResponse(tool_calls=calls)
        msg = r.to_message_dict()
        assert msg["tool_calls"] == calls


class TestBuildPayload:
    def test_basic_payload(self):
        client = LLMGatewayClient(LLMClientConfig(model="test-model"))
        payload = client._build_payload(
            messages=[{"role": "user", "content": "hi"}],
        )
        assert payload["model"] == "test-model"
        assert payload["messages"][0]["content"] == "hi"
        assert payload["stream"] is False
        assert payload["temperature"] == 0.7

    def test_with_tools(self):
        client = LLMGatewayClient()
        tools = [{"type": "function", "function": {"name": "calc"}}]
        payload = client._build_payload(messages=[], tools=tools)
        assert payload["tools"] == tools
        assert payload["tool_choice"] == "auto"

    def test_custom_temperature(self):
        client = LLMGatewayClient()
        payload = client._build_payload(messages=[], temperature=0.1)
        assert payload["temperature"] == 0.1

    def test_stream_flag(self):
        client = LLMGatewayClient()
        payload = client._build_payload(messages=[], stream=True)
        assert payload["stream"] is True


class TestParseResponse:
    def test_normal_response(self):
        client = LLMGatewayClient()
        data = {
            "choices": [{"message": {"content": "Hello"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            "model": "test",
        }
        result = client._parse_response(data, 100.0)
        assert result.content == "Hello"
        assert result.finish_reason == "stop"
        assert result.usage.total_tokens == 15
        assert result.latency_ms == 100.0

    def test_empty_choices(self):
        client = LLMGatewayClient()
        result = client._parse_response({"choices": []}, 50.0)
        assert result.content == ""

    def test_tool_calls_response(self):
        client = LLMGatewayClient()
        data = {
            "choices": [{
                "message": {
                    "content": None,
                    "tool_calls": [{"id": "c1", "function": {"name": "calc"}}],
                },
                "finish_reason": "tool_calls",
            }],
            "usage": {},
        }
        result = client._parse_response(data, 200.0)
        assert result.tool_calls is not None
        assert len(result.tool_calls) == 1


class TestUsageTracking:
    def test_cumulative_usage(self):
        client = LLMGatewayClient()
        client._update_usage(TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15))
        client._update_usage(TokenUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30))
        assert client.cumulative_usage.total_tokens == 45
        assert client.cumulative_usage.prompt_tokens == 30


# ── Integration tests (real LLM) ──


class TestLLMIntegration:
    """Integration tests with real LLM at 127.0.0.1:7225."""

    @pytest.fixture
    def client(self):
        cfg = LLMClientConfig(
            base_url="http://127.0.0.1:7225/v1",
            model="instruct_model",
            timeout_s=30.0,
            max_retries=1,
        )
        return LLMGatewayClient(cfg)

    @pytest.mark.asyncio
    async def test_simple_completion(self, client):
        messages = [{"role": "user", "content": "Say 'hello' and nothing else."}]
        response = await client.chat_completion(messages, max_tokens=32)
        assert response.content is not None
        assert len(response.content) > 0
        assert response.usage.total_tokens > 0
        assert response.latency_ms > 0
        assert client.call_count == 1
        await client.close()

    @pytest.mark.asyncio
    async def test_streaming(self, client):
        messages = [{"role": "user", "content": "Count from 1 to 3."}]
        chunks = []
        async for chunk in client.chat_completion_stream(messages, max_tokens=64):
            chunks.append(chunk)
        assert len(chunks) > 0
        await client.close()

    @pytest.mark.asyncio
    async def test_context_manager(self):
        cfg = LLMClientConfig(
            base_url="http://127.0.0.1:7225/v1",
            model="instruct_model",
            timeout_s=30.0,
        )
        async with LLMGatewayClient(cfg) as client:
            response = await client.chat_completion(
                [{"role": "user", "content": "Hi"}],
                max_tokens=16,
            )
            assert response.content is not None

    @pytest.mark.asyncio
    async def test_connection_error(self):
        cfg = LLMClientConfig(
            base_url="http://127.0.0.1:59999/v1",
            max_retries=0,
            timeout_s=5.0,
        )
        client = LLMGatewayClient(cfg)
        with pytest.raises(LLMClientError):
            await client.chat_completion([{"role": "user", "content": "hi"}])
        await client.close()
