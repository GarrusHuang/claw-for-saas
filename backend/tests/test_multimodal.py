"""
Tests for A4-4i 多模态 LLM 集成.

~12 tests covering:
- TestBuildUserMessageMultimodal: with/without image_blocks → list/str
- TestGatewayMaterialProcessing: image material → image_blocks
- TestVisionFallback: llm_supports_vision=False → text fallback
- TestTokenEstimatorMultimodal: list content → correct token estimate
- TestRuntimeMultimodalMessage: str|list user_message → correct messages
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from agent.prompt import PromptBuilder
from core.token_estimator import _estimate_single_message_tokens, estimate_tokens


# ─── TestBuildUserMessageMultimodal ───


class TestBuildUserMessageMultimodal:
    def setup_method(self):
        self.builder = PromptBuilder()

    def test_no_images_returns_str(self):
        result = self.builder.build_user_message(
            message="hello",
            materials_summary="some text",
        )
        assert isinstance(result, str)
        assert "hello" in result
        assert "<materials>" in result

    def test_no_images_no_materials_returns_str(self):
        result = self.builder.build_user_message(message="hello")
        assert isinstance(result, str)
        assert result == "hello"

    def test_with_images_returns_list(self):
        result = self.builder.build_user_message(
            message="describe this",
            image_blocks=[{"base64": "abc123", "media_type": "image/png"}],
        )
        assert isinstance(result, list)
        # Last block should be the text message
        assert result[-1]["type"] == "text"
        assert result[-1]["text"] == "describe this"

    def test_with_images_and_materials(self):
        result = self.builder.build_user_message(
            message="analyze",
            materials_summary="[doc.pdf]\nSome content",
            image_blocks=[{"base64": "img1", "media_type": "image/jpeg"}],
        )
        assert isinstance(result, list)
        # First block: materials text
        assert result[0]["type"] == "text"
        assert "<materials>" in result[0]["text"]
        # Second block: image
        assert result[1]["type"] == "image_url"
        assert "data:image/jpeg;base64,img1" in result[1]["image_url"]["url"]
        # Third block: user message
        assert result[2]["type"] == "text"
        assert result[2]["text"] == "analyze"

    def test_multiple_images(self):
        result = self.builder.build_user_message(
            message="compare",
            image_blocks=[
                {"base64": "a", "media_type": "image/png"},
                {"base64": "b", "media_type": "image/jpeg"},
            ],
        )
        assert isinstance(result, list)
        image_blocks = [b for b in result if b.get("type") == "image_url"]
        assert len(image_blocks) == 2

    def test_empty_image_blocks_returns_str(self):
        """image_blocks=None or empty list → fallback to str."""
        result = self.builder.build_user_message(
            message="hello",
            image_blocks=None,
        )
        assert isinstance(result, str)


# ─── TestTokenEstimatorMultimodal ───


class TestTokenEstimatorMultimodal:
    def test_list_content_with_text_blocks(self):
        msg = {
            "role": "user",
            "content": [
                {"type": "text", "text": "Hello world"},
                {"type": "text", "text": "More text"},
            ],
        }
        tokens = _estimate_single_message_tokens(msg)
        # 4 (overhead) + text tokens
        expected_text_tokens = estimate_tokens("Hello world") + estimate_tokens("More text")
        assert tokens == 4 + expected_text_tokens

    def test_list_content_with_image_block(self):
        msg = {
            "role": "user",
            "content": [
                {"type": "text", "text": "describe"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
            ],
        }
        tokens = _estimate_single_message_tokens(msg)
        # 4 (overhead) + text tokens + 256 (image)
        expected = 4 + estimate_tokens("describe") + 256
        assert tokens == expected

    def test_list_content_multiple_images(self):
        msg = {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,a"}},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,b"}},
            ],
        }
        tokens = _estimate_single_message_tokens(msg)
        assert tokens == 4 + 256 + 256  # overhead + 2 images

    def test_str_content_unchanged(self):
        """Regular string content should still work."""
        msg = {"role": "user", "content": "Hello world"}
        tokens = _estimate_single_message_tokens(msg)
        assert tokens == 4 + estimate_tokens("Hello world")


# ─── TestRuntimeMultimodalMessage ───


class TestRuntimeMultimodalMessage:
    def test_str_user_message(self):
        """str user_message → standard message."""
        from core.runtime import AgenticRuntime, RuntimeConfig
        from unittest.mock import MagicMock

        runtime = AgenticRuntime(
            llm_client=MagicMock(),
            tool_registry=MagicMock(),
            config=RuntimeConfig(),
        )
        messages = runtime._build_initial_messages(
            system_prompt="You are an AI.",
            user_message="Hello",
            initial_messages=None,
        )
        assert messages[-1] == {"role": "user", "content": "Hello"}

    def test_list_user_message(self):
        """list user_message → multimodal content blocks."""
        from core.runtime import AgenticRuntime, RuntimeConfig
        from unittest.mock import MagicMock

        runtime = AgenticRuntime(
            llm_client=MagicMock(),
            tool_registry=MagicMock(),
            config=RuntimeConfig(),
        )
        content_blocks = [
            {"type": "text", "text": "describe"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
        ]
        messages = runtime._build_initial_messages(
            system_prompt="You are an AI.",
            user_message=content_blocks,
            initial_messages=None,
        )
        assert messages[-1]["role"] == "user"
        assert messages[-1]["content"] == content_blocks
