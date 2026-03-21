"""
Tests for MCP 标准工具接口 (A2 补全).

~25 tests covering:
- TestMCPToolsWithProvider: mock provider, 6 tools normal return
- TestMCPToolsWithoutProvider: no provider → error dict fallback
- TestMCPToolRegistry: 6 tools registered, read_only correct
- TestDefaultMCPProvider: stub returns error + hint
- TestHttpMCPProvider: httpx mock verifies HTTP calls
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from core.context import RequestContext, current_request
from tools.mcp.mcp_tools import (
    mcp_registry,
    get_form_schema,
    get_business_rules,
    get_candidate_types,
    get_protected_values,
    submit_form_data,
    query_data,
    _get_provider,
)
from tools.mcp.defaults import DefaultMCPProvider
from tools.mcp.http_provider import HttpMCPProvider


# ─── Fixtures ───


@pytest.fixture(autouse=True)
def _reset_mcp_context():
    """Reset RequestContext before each test."""
    ctx = RequestContext(mcp_provider=None)
    token = current_request.set(ctx)
    yield
    current_request.reset(token)


class MockMCPProvider:
    """Mock MCP Provider for testing."""

    async def get_form_schema(self, form_type: str) -> dict:
        return {"form_type": form_type, "fields": ["name", "amount"]}

    async def get_business_rules(self, rule_type: str) -> dict:
        return {"rule_type": rule_type, "rules": ["max_amount_1000"]}

    async def get_candidate_types(self, category: str) -> dict:
        return {"category": category, "types": ["type_a", "type_b"]}

    async def get_protected_values(self, context: str) -> dict:
        return {"context": context, "values": {"org_id": "ORG001"}}

    async def submit_form_data(self, form_type: str, data: dict) -> dict:
        return {"status": "submitted", "form_type": form_type}

    async def query_data(self, query_type: str, params: dict) -> dict:
        return {"query_type": query_type, "results": []}


# ─── TestMCPToolRegistry ───


class TestMCPToolRegistry:
    def test_has_six_tools(self):
        names = mcp_registry.get_tool_names()
        assert len(names) == 6

    def test_tool_names(self):
        names = set(mcp_registry.get_tool_names())
        expected = {
            "get_form_schema",
            "get_business_rules",
            "get_candidate_types",
            "get_protected_values",
            "submit_form_data",
            "query_data",
        }
        assert names == expected

    def test_read_only_tools(self):
        """5 tools are read_only, submit_form_data is not."""
        read_only_tools = [
            "get_form_schema",
            "get_business_rules",
            "get_candidate_types",
            "get_protected_values",
            "query_data",
        ]
        for name in read_only_tools:
            assert mcp_registry.is_read_only(name) is True, f"{name} should be read_only"

    def test_submit_form_data_not_read_only(self):
        assert mcp_registry.is_read_only("submit_form_data") is False

    def test_all_tools_have_descriptions(self):
        for tool in mcp_registry.list_tools():
            assert tool.description, f"{tool.name} missing description"


# ─── TestMCPToolsWithProvider ───


class TestMCPToolsWithProvider:
    @pytest.fixture(autouse=True)
    def _set_provider(self):
        self.provider = MockMCPProvider()
        ctx = RequestContext(mcp_provider=self.provider)
        current_request.set(ctx)

    @pytest.mark.asyncio
    async def test_get_form_schema(self):
        result = await get_form_schema(form_type="reimbursement")
        assert result["form_type"] == "reimbursement"
        assert "fields" in result

    @pytest.mark.asyncio
    async def test_get_business_rules(self):
        result = await get_business_rules(rule_type="approval")
        assert result["rule_type"] == "approval"
        assert "rules" in result

    @pytest.mark.asyncio
    async def test_get_candidate_types(self):
        result = await get_candidate_types(category="expense")
        assert result["category"] == "expense"
        assert "types" in result

    @pytest.mark.asyncio
    async def test_get_protected_values(self):
        result = await get_protected_values(context="user_info")
        assert result["context"] == "user_info"
        assert "values" in result

    @pytest.mark.asyncio
    async def test_submit_form_data(self):
        result = await submit_form_data(
            form_type="reimbursement",
            data={"amount": 100},
        )
        assert result["status"] == "submitted"
        assert result["form_type"] == "reimbursement"

    @pytest.mark.asyncio
    async def test_query_data(self):
        result = await query_data(
            query_type="history",
            params={"limit": 10},
        )
        assert result["query_type"] == "history"
        assert "results" in result


# ─── TestMCPToolsWithoutProvider ───


class TestMCPToolsWithoutProvider:
    """No provider set → fallback to DefaultMCPProvider → error dict."""

    @pytest.mark.asyncio
    async def test_get_form_schema_returns_error(self):
        result = await get_form_schema(form_type="any")
        assert "error" in result
        assert result["error"] == "MCP not configured"

    @pytest.mark.asyncio
    async def test_get_business_rules_returns_error(self):
        result = await get_business_rules(rule_type="any")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_submit_form_data_returns_error(self):
        result = await submit_form_data(form_type="any", data={})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_query_data_returns_error(self):
        result = await query_data(query_type="any", params={})
        assert "error" in result


# ─── TestDefaultMCPProvider ───


class TestDefaultMCPProvider:
    @pytest.mark.asyncio
    async def test_all_methods_return_error_and_hint(self):
        provider = DefaultMCPProvider()
        methods = [
            provider.get_form_schema("x"),
            provider.get_business_rules("x"),
            provider.get_candidate_types("x"),
            provider.get_protected_values("x"),
            provider.submit_form_data("x", {}),
            provider.query_data("x", {}),
        ]
        for coro in methods:
            result = await coro
            assert result["error"] == "MCP not configured"
            assert "hint" in result


# ─── TestHttpMCPProvider ───


class TestHttpMCPProvider:
    @pytest.mark.asyncio
    async def test_get_form_schema_calls_correct_endpoint(self):
        provider = HttpMCPProvider(base_url="http://test.local/api")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"fields": ["a"]}
        mock_resp.raise_for_status = MagicMock()

        with patch.object(provider._client, "get", new_callable=AsyncMock, return_value=mock_resp) as mock_get:
            result = await provider.get_form_schema("leave")
            mock_get.assert_called_once_with("/forms/leave/schema")
            assert result == {"fields": ["a"]}

    @pytest.mark.asyncio
    async def test_get_business_rules_calls_correct_endpoint(self):
        provider = HttpMCPProvider(base_url="http://test.local/api")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"rules": []}
        mock_resp.raise_for_status = MagicMock()

        with patch.object(provider._client, "get", new_callable=AsyncMock, return_value=mock_resp) as mock_get:
            result = await provider.get_business_rules("approval")
            mock_get.assert_called_once_with("/rules/approval")

    @pytest.mark.asyncio
    async def test_submit_form_data_posts(self):
        provider = HttpMCPProvider(base_url="http://test.local/api")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": True}
        mock_resp.raise_for_status = MagicMock()

        with patch.object(provider._client, "post", new_callable=AsyncMock, return_value=mock_resp) as mock_post:
            result = await provider.submit_form_data("leave", {"days": 3})
            mock_post.assert_called_once_with("/forms/leave/submit", json={"days": 3})
            assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_query_data_posts(self):
        provider = HttpMCPProvider(base_url="http://test.local/api")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"results": [1, 2]}
        mock_resp.raise_for_status = MagicMock()

        with patch.object(provider._client, "post", new_callable=AsyncMock, return_value=mock_resp) as mock_post:
            result = await provider.query_data("history", {"limit": 5})
            mock_post.assert_called_once_with("/query/history", json={"limit": 5})

    @pytest.mark.asyncio
    async def test_http_error_returns_error_dict(self):
        import httpx
        provider = HttpMCPProvider(base_url="http://test.local/api")
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        error = httpx.HTTPStatusError("not found", request=MagicMock(), response=mock_resp)

        with patch.object(provider._client, "get", new_callable=AsyncMock, side_effect=error):
            result = await provider.get_form_schema("missing")
            assert "error" in result
            assert "404" in result["error"]

    @pytest.mark.asyncio
    async def test_connection_error_returns_error_dict(self):
        provider = HttpMCPProvider(base_url="http://test.local/api")

        with patch.object(provider._client, "get", new_callable=AsyncMock, side_effect=Exception("connection refused")):
            result = await provider.get_candidate_types("x")
            assert "error" in result
            assert "connection refused" in result["error"]


# ─── TestGetProvider ───


class TestGetProvider:
    def test_returns_set_provider(self):
        mock = MockMCPProvider()
        ctx = RequestContext(mcp_provider=mock)
        current_request.set(ctx)
        assert _get_provider() is mock

    def test_returns_default_when_none(self):
        provider = _get_provider()
        assert isinstance(provider, DefaultMCPProvider)
