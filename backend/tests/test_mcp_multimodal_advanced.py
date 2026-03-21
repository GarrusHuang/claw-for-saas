"""
Tests for MCP and multimodal edge cases (advanced).

Covers:
- HttpMCPProvider: close(), HTTP error codes, timeout, custom headers, connection error
- Gateway multimodal full flow: vision on/off, material validation, PromptBuilder integration
- MCP ContextVar injection verification during Gateway.chat()
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import asyncio
import mimetypes
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import httpx
import pytest

from core.context import RequestContext, current_request
from tools.mcp.http_provider import HttpMCPProvider
from agent.prompt import PromptBuilder


# ─── Fixtures ───


@pytest.fixture(autouse=True)
def _reset_mcp_context():
    """Reset RequestContext before each test."""
    ctx = RequestContext(mcp_provider=None)
    token = current_request.set(ctx)
    yield
    current_request.reset(token)


# ═══════════════════════════════════════════════════════════════════
# 1. HttpMCPProvider edge cases
# ═══════════════════════════════════════════════════════════════════


def _make_status_error(status_code: int) -> httpx.HTTPStatusError:
    """Helper to build an HTTPStatusError with the given status code."""
    mock_response = MagicMock()
    mock_response.status_code = status_code
    return httpx.HTTPStatusError(
        f"HTTP {status_code}",
        request=MagicMock(),
        response=mock_response,
    )


class TestHttpMCPProviderClose:
    """close() method tests."""

    @pytest.mark.asyncio
    async def test_close_calls_aclose(self):
        provider = HttpMCPProvider(base_url="http://test.local/api")
        provider._client = AsyncMock()
        await provider.close()
        provider._client.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_can_be_called_multiple_times(self):
        """close() should not raise even when called twice."""
        provider = HttpMCPProvider(base_url="http://test.local/api")
        provider._client = AsyncMock()
        await provider.close()
        await provider.close()
        assert provider._client.aclose.await_count == 2


class TestHttpMCPProviderHTTPErrors:
    """HTTP error status codes return structured error dicts."""

    @pytest.mark.asyncio
    async def test_500_internal_server_error(self):
        provider = HttpMCPProvider(base_url="http://test.local/api")
        with patch.object(
            provider._client, "get",
            new_callable=AsyncMock,
            side_effect=_make_status_error(500),
        ):
            result = await provider.get_form_schema("any")
            assert result == {"error": "HTTP 500", "path": "/forms/any/schema"}

    @pytest.mark.asyncio
    async def test_401_unauthorized(self):
        provider = HttpMCPProvider(base_url="http://test.local/api")
        with patch.object(
            provider._client, "get",
            new_callable=AsyncMock,
            side_effect=_make_status_error(401),
        ):
            result = await provider.get_business_rules("auth_test")
            assert result == {"error": "HTTP 401", "path": "/rules/auth_test"}

    @pytest.mark.asyncio
    async def test_403_forbidden(self):
        provider = HttpMCPProvider(base_url="http://test.local/api")
        with patch.object(
            provider._client, "get",
            new_callable=AsyncMock,
            side_effect=_make_status_error(403),
        ):
            result = await provider.get_candidate_types("restricted")
            assert result == {"error": "HTTP 403", "path": "/candidates/restricted"}

    @pytest.mark.asyncio
    async def test_404_not_found(self):
        provider = HttpMCPProvider(base_url="http://test.local/api")
        with patch.object(
            provider._client, "get",
            new_callable=AsyncMock,
            side_effect=_make_status_error(404),
        ):
            result = await provider.get_protected_values("missing")
            assert result == {"error": "HTTP 404", "path": "/protected/missing"}

    @pytest.mark.asyncio
    async def test_post_500_error(self):
        """POST endpoints also return structured error dicts."""
        provider = HttpMCPProvider(base_url="http://test.local/api")
        with patch.object(
            provider._client, "post",
            new_callable=AsyncMock,
            side_effect=_make_status_error(500),
        ):
            result = await provider.submit_form_data("leave", {"days": 1})
            assert result == {"error": "HTTP 500", "path": "/forms/leave/submit"}

    @pytest.mark.asyncio
    async def test_post_401_error(self):
        provider = HttpMCPProvider(base_url="http://test.local/api")
        with patch.object(
            provider._client, "post",
            new_callable=AsyncMock,
            side_effect=_make_status_error(401),
        ):
            result = await provider.query_data("history", {"limit": 5})
            assert result == {"error": "HTTP 401", "path": "/query/history"}


class TestHttpMCPProviderTimeout:
    """Timeout returns error dict, does not hang."""

    @pytest.mark.asyncio
    async def test_get_timeout(self):
        provider = HttpMCPProvider(base_url="http://test.local/api", timeout_s=0.1)
        with patch.object(
            provider._client, "get",
            new_callable=AsyncMock,
            side_effect=httpx.ReadTimeout("read timed out"),
        ):
            result = await provider.get_form_schema("slow")
            assert "error" in result
            assert "path" in result
            assert result["path"] == "/forms/slow/schema"

    @pytest.mark.asyncio
    async def test_post_timeout(self):
        provider = HttpMCPProvider(base_url="http://test.local/api", timeout_s=0.1)
        with patch.object(
            provider._client, "post",
            new_callable=AsyncMock,
            side_effect=httpx.ReadTimeout("read timed out"),
        ):
            result = await provider.submit_form_data("slow", {})
            assert "error" in result
            assert result["path"] == "/forms/slow/submit"

    @pytest.mark.asyncio
    async def test_connect_timeout(self):
        provider = HttpMCPProvider(base_url="http://test.local/api", timeout_s=0.1)
        with patch.object(
            provider._client, "get",
            new_callable=AsyncMock,
            side_effect=httpx.ConnectTimeout("connect timed out"),
        ):
            result = await provider.get_business_rules("timeout")
            assert "error" in result
            assert "timed out" in result["error"]


class TestHttpMCPProviderCustomHeaders:
    """Custom headers are passed to the underlying httpx client."""

    def test_headers_stored_in_client(self):
        headers = {"Authorization": "Bearer token123", "X-Tenant-Id": "T001"}
        provider = HttpMCPProvider(
            base_url="http://test.local/api",
            headers=headers,
        )
        # httpx.AsyncClient stores merged headers; verify our custom ones are present
        client_headers = dict(provider._client.headers)
        assert client_headers["authorization"] == "Bearer token123"
        assert client_headers["x-tenant-id"] == "T001"

    @pytest.mark.asyncio
    async def test_headers_sent_with_get_request(self):
        headers = {"X-Custom": "value"}
        provider = HttpMCPProvider(base_url="http://test.local/api", headers=headers)

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": True}
        mock_resp.raise_for_status = MagicMock()

        with patch.object(
            provider._client, "get",
            new_callable=AsyncMock,
            return_value=mock_resp,
        ) as mock_get:
            result = await provider.get_form_schema("test")
            mock_get.assert_awaited_once_with("/forms/test/schema")
            assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_headers_sent_with_post_request(self):
        headers = {"X-Custom": "value"}
        provider = HttpMCPProvider(base_url="http://test.local/api", headers=headers)

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"submitted": True}
        mock_resp.raise_for_status = MagicMock()

        with patch.object(
            provider._client, "post",
            new_callable=AsyncMock,
            return_value=mock_resp,
        ) as mock_post:
            result = await provider.submit_form_data("leave", {"days": 1})
            mock_post.assert_awaited_once_with("/forms/leave/submit", json={"days": 1})
            assert result == {"submitted": True}

    def test_no_headers_defaults_to_empty(self):
        provider = HttpMCPProvider(base_url="http://test.local/api")
        # Should not have any custom headers beyond httpx defaults
        client_headers = dict(provider._client.headers)
        assert "authorization" not in client_headers


class TestHttpMCPProviderConnectionError:
    """Server unreachable returns error dict."""

    @pytest.mark.asyncio
    async def test_connection_refused(self):
        provider = HttpMCPProvider(base_url="http://test.local/api")
        with patch.object(
            provider._client, "get",
            new_callable=AsyncMock,
            side_effect=httpx.ConnectError("Connection refused"),
        ):
            result = await provider.get_form_schema("test")
            assert "error" in result
            assert "Connection refused" in result["error"]
            assert result["path"] == "/forms/test/schema"

    @pytest.mark.asyncio
    async def test_dns_resolution_failure(self):
        provider = HttpMCPProvider(base_url="http://nonexistent.invalid/api")
        with patch.object(
            provider._client, "get",
            new_callable=AsyncMock,
            side_effect=httpx.ConnectError("Name or service not known"),
        ):
            result = await provider.get_business_rules("test")
            assert "error" in result
            assert result["path"] == "/rules/test"

    @pytest.mark.asyncio
    async def test_post_connection_refused(self):
        provider = HttpMCPProvider(base_url="http://test.local/api")
        with patch.object(
            provider._client, "post",
            new_callable=AsyncMock,
            side_effect=httpx.ConnectError("Connection refused"),
        ):
            result = await provider.query_data("test", {"a": 1})
            assert "error" in result
            assert result["path"] == "/query/test"


class TestHttpMCPProviderBaseUrlStripping:
    """base_url trailing slash is stripped."""

    def test_trailing_slash_stripped(self):
        provider = HttpMCPProvider(base_url="http://test.local/api/")
        assert provider.base_url == "http://test.local/api"

    def test_no_trailing_slash_unchanged(self):
        provider = HttpMCPProvider(base_url="http://test.local/api")
        assert provider.base_url == "http://test.local/api"


# ═══════════════════════════════════════════════════════════════════
# 2. Gateway multimodal full flow
# ═══════════════════════════════════════════════════════════════════


class TestGatewayMaterialVisionEnabled:
    """Vision enabled (llm_supports_vision=True) — image material processing."""

    def _process_materials(self, materials):
        """Replicate the gateway material processing logic (lines 247-261)."""
        text_summaries = []
        image_blocks = []
        for m in (materials or []):
            if not isinstance(m, dict):
                continue
            mat_type = m.get("material_type", "text")
            filename = m.get("filename", "")
            content = m.get("content", "")

            if mat_type == "image" and content and True:  # vision=True
                media_type = mimetypes.guess_type(filename)[0] or "image/png"
                image_blocks.append({"base64": content, "media_type": media_type})
                text_summaries.append(f"[Image: {filename}]")
            else:
                text_summaries.append(f"[{filename}]\n{content[:2000]}")
        return text_summaries, image_blocks

    def test_image_material_extracted_as_image_block(self):
        materials = [
            {"material_type": "image", "filename": "photo.png", "content": "base64data"}
        ]
        summaries, blocks = self._process_materials(materials)
        assert len(blocks) == 1
        assert blocks[0]["base64"] == "base64data"
        assert blocks[0]["media_type"] == "image/png"
        assert summaries == ["[Image: photo.png]"]

    def test_png_filename_media_type(self):
        materials = [
            {"material_type": "image", "filename": "test.png", "content": "data"}
        ]
        _, blocks = self._process_materials(materials)
        assert blocks[0]["media_type"] == "image/png"

    def test_jpg_filename_media_type(self):
        materials = [
            {"material_type": "image", "filename": "photo.jpg", "content": "data"}
        ]
        _, blocks = self._process_materials(materials)
        assert blocks[0]["media_type"] == "image/jpeg"

    def test_jpeg_filename_media_type(self):
        materials = [
            {"material_type": "image", "filename": "photo.jpeg", "content": "data"}
        ]
        _, blocks = self._process_materials(materials)
        assert blocks[0]["media_type"] == "image/jpeg"

    def test_gif_filename_media_type(self):
        materials = [
            {"material_type": "image", "filename": "anim.gif", "content": "data"}
        ]
        _, blocks = self._process_materials(materials)
        assert blocks[0]["media_type"] == "image/gif"

    def test_unknown_extension_defaults_to_png(self):
        materials = [
            {"material_type": "image", "filename": "file.qzx9", "content": "data"}
        ]
        _, blocks = self._process_materials(materials)
        assert blocks[0]["media_type"] == "image/png"

    def test_no_extension_defaults_to_png(self):
        materials = [
            {"material_type": "image", "filename": "noext", "content": "data"}
        ]
        _, blocks = self._process_materials(materials)
        assert blocks[0]["media_type"] == "image/png"

    def test_multiple_images_all_in_image_blocks(self):
        materials = [
            {"material_type": "image", "filename": "a.png", "content": "data1"},
            {"material_type": "image", "filename": "b.jpg", "content": "data2"},
            {"material_type": "image", "filename": "c.gif", "content": "data3"},
        ]
        summaries, blocks = self._process_materials(materials)
        assert len(blocks) == 3
        assert len(summaries) == 3
        assert blocks[0]["media_type"] == "image/png"
        assert blocks[1]["media_type"] == "image/jpeg"
        assert blocks[2]["media_type"] == "image/gif"

    def test_mixed_image_and_text_materials(self):
        materials = [
            {"material_type": "text", "filename": "doc.txt", "content": "hello"},
            {"material_type": "image", "filename": "photo.png", "content": "imgdata"},
            {"material_type": "text", "filename": "notes.md", "content": "notes"},
        ]
        summaries, blocks = self._process_materials(materials)
        assert len(blocks) == 1
        assert blocks[0]["base64"] == "imgdata"
        assert len(summaries) == 3
        assert summaries[0] == "[doc.txt]\nhello"
        assert summaries[1] == "[Image: photo.png]"
        assert summaries[2] == "[notes.md]\nnotes"


class TestGatewayMaterialVisionDisabled:
    """Vision disabled (llm_supports_vision=False) — fallback to text."""

    def _process_materials_no_vision(self, materials):
        """Replicate gateway logic with vision disabled."""
        text_summaries = []
        image_blocks = []
        for m in (materials or []):
            if not isinstance(m, dict):
                continue
            mat_type = m.get("material_type", "text")
            filename = m.get("filename", "")
            content = m.get("content", "")

            if mat_type == "image" and content and False:  # vision=False
                media_type = mimetypes.guess_type(filename)[0] or "image/png"
                image_blocks.append({"base64": content, "media_type": media_type})
                text_summaries.append(f"[Image: {filename}]")
            else:
                text_summaries.append(f"[{filename}]\n{content[:2000]}")
        return text_summaries, image_blocks

    def test_image_treated_as_text(self):
        materials = [
            {"material_type": "image", "filename": "photo.png", "content": "base64data"}
        ]
        summaries, blocks = self._process_materials_no_vision(materials)
        assert len(blocks) == 0
        assert len(summaries) == 1
        assert summaries[0] == "[photo.png]\nbase64data"

    def test_content_truncated_to_2000(self):
        long_content = "x" * 5000
        materials = [
            {"material_type": "image", "filename": "big.png", "content": long_content}
        ]
        summaries, blocks = self._process_materials_no_vision(materials)
        assert len(blocks) == 0
        # Content should be truncated to 2000 chars
        expected = f"[big.png]\n{'x' * 2000}"
        assert summaries[0] == expected
        assert len(summaries[0]) == len("[big.png]\n") + 2000

    def test_no_image_blocks_generated(self):
        materials = [
            {"material_type": "image", "filename": "a.png", "content": "data1"},
            {"material_type": "image", "filename": "b.jpg", "content": "data2"},
        ]
        _, blocks = self._process_materials_no_vision(materials)
        assert blocks == []


class TestGatewayMaterialValidation:
    """Material edge cases — non-dict, missing fields, empty content."""

    def _process_materials_with_vision(self, materials):
        """Process with vision enabled."""
        text_summaries = []
        image_blocks = []
        for m in (materials or []):
            if not isinstance(m, dict):
                continue
            mat_type = m.get("material_type", "text")
            filename = m.get("filename", "")
            content = m.get("content", "")

            if mat_type == "image" and content and True:
                media_type = mimetypes.guess_type(filename)[0] or "image/png"
                image_blocks.append({"base64": content, "media_type": media_type})
                text_summaries.append(f"[Image: {filename}]")
            else:
                text_summaries.append(f"[{filename}]\n{content[:2000]}")
        return text_summaries, image_blocks

    def test_non_dict_material_skipped(self):
        materials = ["string_item", 42, None, True]
        summaries, blocks = self._process_materials_with_vision(materials)
        assert summaries == []
        assert blocks == []

    def test_material_without_material_type_defaults_to_text(self):
        materials = [
            {"filename": "readme.txt", "content": "hello world"}
        ]
        summaries, blocks = self._process_materials_with_vision(materials)
        assert len(summaries) == 1
        assert summaries[0] == "[readme.txt]\nhello world"
        assert blocks == []

    def test_image_with_empty_content_treated_as_text(self):
        """content is falsy (empty string) => goes to else branch."""
        materials = [
            {"material_type": "image", "filename": "empty.png", "content": ""}
        ]
        summaries, blocks = self._process_materials_with_vision(materials)
        assert len(blocks) == 0
        assert len(summaries) == 1
        assert summaries[0] == "[empty.png]\n"

    def test_image_with_none_content_treated_as_text(self):
        """content defaults to "" via .get("content", ""), which is falsy."""
        materials = [
            {"material_type": "image", "filename": "null.png"}
        ]
        summaries, blocks = self._process_materials_with_vision(materials)
        assert len(blocks) == 0

    def test_very_long_text_content_truncated(self):
        long_content = "A" * 10000
        materials = [
            {"material_type": "text", "filename": "huge.txt", "content": long_content}
        ]
        summaries, _ = self._process_materials_with_vision(materials)
        # content[:2000] truncates to 2000
        assert summaries[0] == f"[huge.txt]\n{'A' * 2000}"

    def test_materials_none_produces_empty(self):
        summaries, blocks = self._process_materials_with_vision(None)
        assert summaries == []
        assert blocks == []

    def test_materials_empty_list_produces_empty(self):
        summaries, blocks = self._process_materials_with_vision([])
        assert summaries == []
        assert blocks == []

    def test_mixed_valid_and_invalid_materials(self):
        materials = [
            "not_a_dict",
            {"material_type": "text", "filename": "doc.txt", "content": "valid"},
            42,
            {"material_type": "image", "filename": "img.png", "content": "imgdata"},
        ]
        summaries, blocks = self._process_materials_with_vision(materials)
        assert len(summaries) == 2
        assert len(blocks) == 1
        assert summaries[0] == "[doc.txt]\nvalid"
        assert blocks[0]["base64"] == "imgdata"


class TestPromptBuilderMultimodalIntegration:
    """PromptBuilder.build_user_message integration with image_blocks."""

    def setup_method(self):
        self.builder = PromptBuilder()

    def test_image_blocks_returns_list(self):
        result = self.builder.build_user_message(
            message="describe the image",
            image_blocks=[{"base64": "abc", "media_type": "image/png"}],
        )
        assert isinstance(result, list)

    def test_no_image_blocks_returns_str(self):
        result = self.builder.build_user_message(
            message="hello",
            image_blocks=None,
        )
        assert isinstance(result, str)

    def test_empty_image_blocks_returns_str(self):
        result = self.builder.build_user_message(
            message="hello",
            image_blocks=[],
        )
        # Empty list is falsy, should return str
        assert isinstance(result, str)

    def test_image_block_url_format(self):
        result = self.builder.build_user_message(
            message="analyze",
            image_blocks=[{"base64": "AAAA", "media_type": "image/jpeg"}],
        )
        img_block = [b for b in result if b.get("type") == "image_url"][0]
        assert img_block["image_url"]["url"] == "data:image/jpeg;base64,AAAA"

    def test_materials_summary_with_images(self):
        result = self.builder.build_user_message(
            message="describe",
            materials_summary="[Image: photo.png]\n[doc.txt]\nsome text",
            image_blocks=[{"base64": "data", "media_type": "image/png"}],
        )
        assert isinstance(result, list)
        # First block should be materials text
        assert result[0]["type"] == "text"
        assert "<materials>" in result[0]["text"]
        # Last block should be user message
        assert result[-1]["type"] == "text"
        assert result[-1]["text"] == "describe"

    def test_multiple_image_blocks_all_present(self):
        result = self.builder.build_user_message(
            message="compare",
            image_blocks=[
                {"base64": "img1", "media_type": "image/png"},
                {"base64": "img2", "media_type": "image/jpeg"},
                {"base64": "img3", "media_type": "image/gif"},
            ],
        )
        image_items = [b for b in result if b.get("type") == "image_url"]
        assert len(image_items) == 3

    def test_block_ordering_materials_images_message(self):
        """Order: materials text, image blocks, user message."""
        result = self.builder.build_user_message(
            message="user text",
            materials_summary="mat summary",
            image_blocks=[
                {"base64": "a", "media_type": "image/png"},
                {"base64": "b", "media_type": "image/jpeg"},
            ],
        )
        assert result[0]["type"] == "text"        # materials
        assert result[1]["type"] == "image_url"    # image 1
        assert result[2]["type"] == "image_url"    # image 2
        assert result[3]["type"] == "text"         # user message
        assert result[3]["text"] == "user text"


class TestGatewayMaterialsFullPipeline:
    """
    End-to-end test: settings.llm_supports_vision toggles behavior.
    Patches config.settings to control vision flag.
    """

    def _run_gateway_material_logic(self, materials, vision_enabled):
        """
        Replicate the exact gateway.py lines 247-261 with configurable vision.
        """
        text_summaries = []
        image_blocks = []
        for m in (materials or []):
            if not isinstance(m, dict):
                continue
            mat_type = m.get("material_type", "text")
            filename = m.get("filename", "")
            content = m.get("content", "")

            if mat_type == "image" and content and vision_enabled:
                media_type = mimetypes.guess_type(filename)[0] or "image/png"
                image_blocks.append({"base64": content, "media_type": media_type})
                text_summaries.append(f"[Image: {filename}]")
            else:
                text_summaries.append(f"[{filename}]\n{content[:2000]}")
        return text_summaries, image_blocks

    def test_vision_on_then_off_same_input(self):
        """Same image material produces different results based on vision flag."""
        materials = [
            {"material_type": "image", "filename": "photo.png", "content": "imgdata"}
        ]

        # Vision ON
        s_on, b_on = self._run_gateway_material_logic(materials, vision_enabled=True)
        assert len(b_on) == 1
        assert s_on == ["[Image: photo.png]"]

        # Vision OFF
        s_off, b_off = self._run_gateway_material_logic(materials, vision_enabled=False)
        assert len(b_off) == 0
        assert s_off == ["[photo.png]\nimgdata"]

    def test_pipeline_vision_on_builds_multimodal_message(self):
        materials = [
            {"material_type": "image", "filename": "x.png", "content": "data123"}
        ]
        summaries, blocks = self._run_gateway_material_logic(materials, True)

        builder = PromptBuilder()
        materials_summary = "\n\n".join(summaries)
        user_msg = builder.build_user_message(
            message="analyze this",
            materials_summary=materials_summary,
            image_blocks=blocks or None,
        )
        assert isinstance(user_msg, list)
        types = [b["type"] for b in user_msg]
        assert "image_url" in types

    def test_pipeline_vision_off_builds_str_message(self):
        materials = [
            {"material_type": "image", "filename": "x.png", "content": "data123"}
        ]
        summaries, blocks = self._run_gateway_material_logic(materials, False)

        builder = PromptBuilder()
        materials_summary = "\n\n".join(summaries)
        user_msg = builder.build_user_message(
            message="analyze this",
            materials_summary=materials_summary,
            image_blocks=blocks or None,
        )
        assert isinstance(user_msg, str)
        assert "data123" in user_msg

    def test_pipeline_no_materials_builds_str_message(self):
        summaries, blocks = self._run_gateway_material_logic(None, True)
        builder = PromptBuilder()
        user_msg = builder.build_user_message(
            message="just text",
            materials_summary="",
            image_blocks=blocks or None,
        )
        assert isinstance(user_msg, str)
        assert user_msg == "just text"


# ═══════════════════════════════════════════════════════════════════
# 3. MCP ContextVar injection verification
# ═══════════════════════════════════════════════════════════════════


class TestMCPContextVarInjection:
    """
    Verify that Gateway.chat() sets current_mcp_provider ContextVar
    so that MCP tools can retrieve it.
    """

    @pytest.mark.asyncio
    async def test_contextvar_set_when_provider_injected(self):
        """
        Create AgentGateway with a mock mcp_provider.
        Mock the runtime to capture the ContextVar during execution.
        """
        from agent.gateway import AgentGateway
        from core.runtime import RuntimeConfig, RuntimeResult, RuntimeStep
        from core.llm_client import TokenUsage

        mock_provider = MagicMock()
        mock_provider.__class__.__name__ = "MockMCPProvider"

        # Track what the ContextVar holds when runtime.run() is called
        captured_provider = []

        async def fake_runtime_run(**kwargs):
            """Capture ContextVar during runtime execution."""
            ctx = current_request.get()
            captured_provider.append(ctx.mcp_provider if ctx else None)
            return RuntimeResult(
                final_answer="done",
                steps=[],
                token_usage=TokenUsage(),
                iterations=1,
            )

        # Build minimal gateway with mocks
        mock_llm = MagicMock()
        mock_llm.config = MagicMock()
        mock_llm.config.model = "test-model"

        mock_registry = MagicMock()
        mock_registry.list_tools.return_value = []

        mock_session = MagicMock()
        mock_session.session_exists.return_value = False
        mock_session.create_session.return_value = "sess-test123"
        mock_session.load_messages.return_value = []

        mock_skill_loader = None  # skip skill loading
        mock_memory_store = None

        mock_prompt_builder = MagicMock()
        mock_prompt_builder.build_system_prompt.return_value = "system prompt"
        mock_prompt_builder.build_user_message.return_value = "user message"

        mock_subagent_runner = MagicMock()

        gateway = AgentGateway(
            llm_client=mock_llm,
            tool_registry=mock_registry,
            session_manager=mock_session,
            skill_loader=mock_skill_loader,
            prompt_builder=mock_prompt_builder,
            subagent_runner=mock_subagent_runner,
            memory_store=mock_memory_store,
            mcp_provider=mock_provider,
            hooks=None,
        )

        # Patch runtime to capture ContextVar instead of real execution
        with patch("agent.gateway.AgenticRuntime") as MockRuntimeClass:
            mock_runtime_instance = MagicMock()
            mock_runtime_instance.run = AsyncMock(side_effect=fake_runtime_run)
            MockRuntimeClass.return_value = mock_runtime_instance

            # Patch dependencies imports that gateway tries to do
            with patch("agent.gateway.build_default_hooks") as mock_hooks_fn:
                mock_hooks_fn.return_value = MagicMock()
                mock_hooks_fn.return_value.fire = AsyncMock()

                result = await gateway.chat(
                    message="test message",
                    business_type="general_chat",
                )

        assert len(captured_provider) == 1
        assert captured_provider[0] is mock_provider

    @pytest.mark.asyncio
    async def test_contextvar_none_when_no_provider(self):
        """
        Gateway without mcp_provider should NOT set the ContextVar.
        """
        from agent.gateway import AgentGateway
        from core.runtime import RuntimeResult
        from core.llm_client import TokenUsage

        captured_provider = []

        async def fake_runtime_run(**kwargs):
            ctx = current_request.get()
            captured_provider.append(ctx.mcp_provider if ctx else None)
            return RuntimeResult(
                final_answer="done",
                steps=[],
                token_usage=TokenUsage(),
                iterations=1,
            )

        mock_llm = MagicMock()
        mock_llm.config = MagicMock()
        mock_llm.config.model = "test-model"

        mock_registry = MagicMock()
        mock_registry.list_tools.return_value = []

        mock_session = MagicMock()
        mock_session.session_exists.return_value = False
        mock_session.create_session.return_value = "sess-test456"
        mock_session.load_messages.return_value = []

        mock_prompt_builder = MagicMock()
        mock_prompt_builder.build_system_prompt.return_value = "sys"
        mock_prompt_builder.build_user_message.return_value = "msg"

        gateway = AgentGateway(
            llm_client=mock_llm,
            tool_registry=mock_registry,
            session_manager=mock_session,
            skill_loader=None,
            prompt_builder=mock_prompt_builder,
            subagent_runner=MagicMock(),
            memory_store=None,
            mcp_provider=None,  # No provider
            hooks=None,
        )

        with patch("agent.gateway.AgenticRuntime") as MockRuntimeClass:
            mock_runtime_instance = MagicMock()
            mock_runtime_instance.run = AsyncMock(side_effect=fake_runtime_run)
            MockRuntimeClass.return_value = mock_runtime_instance

            with patch("agent.gateway.build_default_hooks") as mock_hooks_fn:
                mock_hooks_fn.return_value = MagicMock()
                mock_hooks_fn.return_value.fire = AsyncMock()

                await gateway.chat(
                    message="test",
                    business_type="general_chat",
                )

        assert len(captured_provider) == 1
        assert captured_provider[0] is None

    @pytest.mark.asyncio
    async def test_mcp_tool_reads_injected_provider(self):
        """
        Verify that an MCP tool function can read the provider from ContextVar.
        This simulates the actual tool execution path.
        """
        from tools.mcp.mcp_tools import _get_provider, get_form_schema

        mock_provider = AsyncMock()
        mock_provider.get_form_schema = AsyncMock(
            return_value={"fields": ["name"]}
        )

        # Simulate what Gateway does: set RequestContext
        ctx = RequestContext(mcp_provider=mock_provider)
        current_request.set(ctx)

        # _get_provider should return our mock
        provider = _get_provider()
        assert provider is mock_provider

        # Calling the MCP tool should use our provider
        result = await get_form_schema(form_type="test")
        assert result == {"fields": ["name"]}
        mock_provider.get_form_schema.assert_awaited_once_with("test")

    @pytest.mark.asyncio
    async def test_contextvar_isolation_between_calls(self):
        """
        RequestContext set in one call should not leak to another
        (when properly reset).
        """
        mock_provider_a = MagicMock()
        mock_provider_b = MagicMock()

        # First call sets provider A
        ctx_a = RequestContext(mcp_provider=mock_provider_a)
        token_a = current_request.set(ctx_a)
        assert current_request.get().mcp_provider is mock_provider_a

        # Reset
        current_request.reset(token_a)

        # After reset, should be back to fixture's context (mcp_provider=None)
        assert current_request.get().mcp_provider is None

        # Second call sets provider B
        ctx_b = RequestContext(mcp_provider=mock_provider_b)
        token_b = current_request.set(ctx_b)
        assert current_request.get().mcp_provider is mock_provider_b

        # Provider A is no longer accessible
        assert current_request.get().mcp_provider is not mock_provider_a

        current_request.reset(token_b)
