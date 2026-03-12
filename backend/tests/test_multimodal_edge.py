"""
Tests for multimodal edge cases — coverage gaps in TokenEstimator,
PromptBuilder, Runtime, and Gateway material processing.

Covers:
1. TokenEstimator list content edge cases (empty, malformed, unknown types, cache)
2. PromptBuilder.build_user_message() malformed image_blocks
3. Runtime._build_initial_messages() multimodal scenarios
4. Gateway material processing edge cases (filenames, formats, empty bytes)
"""
import sys
import os
import base64
import mimetypes
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from core.token_estimator import (
    _estimate_single_message_tokens,
    estimate_messages_tokens,
    estimate_tokens,
    invalidate_cache,
)
from agent.prompt import PromptBuilder
from core.runtime import AgenticRuntime, RuntimeConfig


# ============================================================
# 1. TokenEstimator List Content Edge Cases
# ============================================================


class TestTokenEstimatorListEdgeCases:
    """HIGH PRIORITY: edge cases for list-type content in messages."""

    def setup_method(self):
        invalidate_cache()

    def test_empty_list_content_returns_base_overhead(self):
        """Empty list content [] should return only the base 4-token overhead."""
        msg = {"role": "user", "content": []}
        tokens = _estimate_single_message_tokens(msg)
        # Empty list is falsy, so `if content:` is False -> only overhead
        assert tokens == 4

    def test_list_block_missing_type_key(self):
        """Block dict without 'type' key should be handled gracefully (skipped)."""
        msg = {"role": "user", "content": [{"text": "hello"}]}
        # Should not crash; block lacks "type" so neither text nor image branch fires
        tokens = _estimate_single_message_tokens(msg)
        assert tokens == 4  # overhead only, block contributes nothing

    def test_unknown_block_type(self):
        """Block with unknown type should not crash, just be skipped."""
        msg = {
            "role": "user",
            "content": [{"type": "unknown", "data": "some data"}],
        }
        tokens = _estimate_single_message_tokens(msg)
        assert tokens == 4  # overhead only

    def test_text_block_empty_string(self):
        """Text block with empty string should contribute 0 text tokens."""
        msg = {"role": "user", "content": [{"type": "text", "text": ""}]}
        tokens = _estimate_single_message_tokens(msg)
        # estimate_tokens("") returns 0
        assert tokens == 4

    def test_image_block_missing_image_url_key(self):
        """Image block without 'image_url' key should not crash."""
        msg = {"role": "user", "content": [{"type": "image_url"}]}
        tokens = _estimate_single_message_tokens(msg)
        # Still gets the 256 estimate for image_url type
        assert tokens == 4 + 256

    def test_image_block_malformed_image_url_missing_url(self):
        """Image block with empty image_url dict (missing 'url') should not crash."""
        msg = {
            "role": "user",
            "content": [{"type": "image_url", "image_url": {}}],
        }
        tokens = _estimate_single_message_tokens(msg)
        assert tokens == 4 + 256

    def test_many_images_10(self):
        """10 images should give 10 * 256 = 2560 image tokens."""
        blocks = [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,img{i}"}}
            for i in range(10)
        ]
        msg = {"role": "user", "content": blocks}
        tokens = _estimate_single_message_tokens(msg)
        assert tokens == 4 + (10 * 256)

    def test_many_images_20(self):
        """20 images should give 20 * 256 = 5120 image tokens."""
        blocks = [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,img{i}"}}
            for i in range(20)
        ]
        msg = {"role": "user", "content": blocks}
        tokens = _estimate_single_message_tokens(msg)
        assert tokens == 4 + (20 * 256)

    def test_mixed_blocks_text_image_text_image(self):
        """4+ blocks: text + image + text + image all counted correctly."""
        blocks = [
            {"type": "text", "text": "First text"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,a"}},
            {"type": "text", "text": "Second text"},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,b"}},
        ]
        msg = {"role": "user", "content": blocks}
        tokens = _estimate_single_message_tokens(msg)
        expected = (
            4
            + estimate_tokens("First text")
            + 256
            + estimate_tokens("Second text")
            + 256
        )
        assert tokens == expected

    def test_tool_response_with_list_content(self):
        """Tool response message with list content (unusual but should not crash)."""
        msg = {
            "role": "tool",
            "content": [
                {"type": "text", "text": "tool output"},
            ],
        }
        tokens = _estimate_single_message_tokens(msg)
        # role == "tool" but content is a list, so the isinstance(content, list)
        # branch triggers before the role == "tool" branch
        expected = 4 + estimate_tokens("tool output")
        assert tokens == expected

    def test_cache_returns_same_result(self):
        """Same message called twice should return the same cached result."""
        invalidate_cache()
        msg = {
            "role": "user",
            "content": [
                {"type": "text", "text": "cached test"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,x"}},
            ],
        }
        first_call = _estimate_single_message_tokens(msg)
        second_call = _estimate_single_message_tokens(msg)
        assert first_call == second_call

    def test_none_content_does_not_crash(self):
        """content=None should not crash (None is falsy)."""
        msg = {"role": "user", "content": None}
        tokens = _estimate_single_message_tokens(msg)
        # None is falsy, so only base overhead
        assert tokens == 4

    def test_missing_content_key(self):
        """Message with no 'content' key at all should not crash."""
        msg = {"role": "user"}
        tokens = _estimate_single_message_tokens(msg)
        # .get("content", "") returns "" which is falsy
        assert tokens == 4

    def test_list_with_non_dict_block(self):
        """List content with a non-dict element (e.g. string) should not crash."""
        msg = {"role": "user", "content": ["just a string", 42]}
        tokens = _estimate_single_message_tokens(msg)
        # The isinstance(block, dict) check skips non-dict blocks
        assert tokens == 4

    def test_estimate_messages_tokens_with_multimodal(self):
        """estimate_messages_tokens works with list-content messages."""
        msgs = [
            {"role": "system", "content": "You are helpful."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Look at this"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
                ],
            },
        ]
        invalidate_cache()
        total = estimate_messages_tokens(msgs)
        # system msg overhead + text tokens + user msg overhead + text + 256
        assert total > 4 + 4 + 256


# ============================================================
# 2. PromptBuilder.build_user_message() Malformed image_blocks
# ============================================================


class TestBuildUserMessageMalformedImages:
    """Edge cases for PromptBuilder.build_user_message with bad image_blocks."""

    def setup_method(self):
        self.builder = PromptBuilder()

    def test_empty_dict_in_image_blocks_raises_key_error(self):
        """image_blocks=[{}] should raise KeyError due to missing 'media_type'."""
        with pytest.raises(KeyError):
            self.builder.build_user_message(
                message="test",
                image_blocks=[{}],
            )

    def test_missing_media_type_key_raises_key_error(self):
        """image_blocks with missing media_type should raise KeyError."""
        with pytest.raises(KeyError):
            self.builder.build_user_message(
                message="test",
                image_blocks=[{"base64": "data"}],
            )

    def test_missing_base64_key_raises_key_error(self):
        """image_blocks with missing base64 should raise KeyError."""
        with pytest.raises(KeyError):
            self.builder.build_user_message(
                message="test",
                image_blocks=[{"media_type": "image/png"}],
            )

    def test_empty_base64_string(self):
        """Empty base64 string should still produce a valid block structure."""
        result = self.builder.build_user_message(
            message="test",
            image_blocks=[{"base64": "", "media_type": "image/png"}],
        )
        assert isinstance(result, list)
        img_block = [b for b in result if b.get("type") == "image_url"][0]
        assert img_block["image_url"]["url"] == "data:image/png;base64,"

    def test_non_standard_media_type_webp(self):
        """image/webp media type should be passed through."""
        result = self.builder.build_user_message(
            message="test",
            image_blocks=[{"base64": "abc", "media_type": "image/webp"}],
        )
        img_block = [b for b in result if b.get("type") == "image_url"][0]
        assert "image/webp" in img_block["image_url"]["url"]

    def test_non_standard_media_type_svg(self):
        """image/svg+xml media type should be passed through."""
        result = self.builder.build_user_message(
            message="test",
            image_blocks=[{"base64": "abc", "media_type": "image/svg+xml"}],
        )
        img_block = [b for b in result if b.get("type") == "image_url"][0]
        assert "image/svg+xml" in img_block["image_url"]["url"]

    def test_non_standard_media_type_bmp(self):
        """image/bmp media type should be passed through."""
        result = self.builder.build_user_message(
            message="test",
            image_blocks=[{"base64": "abc", "media_type": "image/bmp"}],
        )
        img_block = [b for b in result if b.get("type") == "image_url"][0]
        assert "image/bmp" in img_block["image_url"]["url"]

    def test_very_long_base64_string(self):
        """Simulate a large image (100KB+ base64) — should not crash."""
        large_b64 = "A" * 150_000  # ~112 KB of raw base64
        result = self.builder.build_user_message(
            message="describe",
            image_blocks=[{"base64": large_b64, "media_type": "image/png"}],
        )
        assert isinstance(result, list)
        img_block = [b for b in result if b.get("type") == "image_url"][0]
        assert len(img_block["image_url"]["url"]) > 150_000

    def test_very_long_message_text_with_images(self):
        """10K+ character message combined with images should work."""
        long_text = "A" * 12_000
        result = self.builder.build_user_message(
            message=long_text,
            image_blocks=[{"base64": "abc", "media_type": "image/png"}],
        )
        assert isinstance(result, list)
        text_block = result[-1]
        assert text_block["type"] == "text"
        assert len(text_block["text"]) == 12_000

    def test_ordering_text_after_images(self):
        """User text block must come AFTER image blocks in the output list."""
        result = self.builder.build_user_message(
            message="final text",
            image_blocks=[
                {"base64": "img1", "media_type": "image/png"},
                {"base64": "img2", "media_type": "image/jpeg"},
            ],
        )
        assert isinstance(result, list)
        # Last block is always the user text message
        assert result[-1] == {"type": "text", "text": "final text"}
        # Image blocks come before the last text block
        for block in result[:-1]:
            assert block["type"] == "image_url"

    def test_ordering_with_materials_summary(self):
        """With materials_summary: materials text first, then images, then user text last."""
        result = self.builder.build_user_message(
            message="analyze this",
            materials_summary="some document text",
            image_blocks=[{"base64": "img1", "media_type": "image/png"}],
        )
        assert isinstance(result, list)
        assert len(result) == 3
        # First: materials text
        assert result[0]["type"] == "text"
        assert "<materials>" in result[0]["text"]
        # Second: image
        assert result[1]["type"] == "image_url"
        # Third: user message
        assert result[2]["type"] == "text"
        assert result[2]["text"] == "analyze this"

    def test_multiple_malformed_blocks_first_raises(self):
        """Multiple blocks where first is malformed should raise."""
        with pytest.raises(KeyError):
            self.builder.build_user_message(
                message="test",
                image_blocks=[
                    {"base64": "good", "media_type": "image/png"},
                    {},  # malformed
                ],
            )


# ============================================================
# 3. Runtime._build_initial_messages() Multimodal Scenarios
# ============================================================


class TestRuntimeBuildInitialMessagesMultimodal:
    """Edge cases for Runtime._build_initial_messages with multimodal content."""

    def _make_runtime(self):
        return AgenticRuntime(
            llm_client=MagicMock(),
            tool_registry=MagicMock(),
            config=RuntimeConfig(),
        )

    def test_list_user_message_with_nonempty_initial_messages(self):
        """list user_message combined with 5+ initial_messages."""
        runtime = self._make_runtime()
        initial = [
            {"role": "user", "content": f"msg {i}"}
            for i in range(5)
        ]
        content_blocks = [
            {"type": "text", "text": "describe"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
        ]
        messages = runtime._build_initial_messages(
            system_prompt="System",
            user_message=content_blocks,
            initial_messages=initial,
        )
        # system + 5 initial + 1 user = 7
        assert len(messages) == 7
        assert messages[0]["role"] == "system"
        assert messages[-1]["role"] == "user"
        assert messages[-1]["content"] == content_blocks

    def test_initial_messages_with_list_content_blocks(self):
        """initial_messages can themselves contain list content blocks."""
        runtime = self._make_runtime()
        initial = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "previous multimodal"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,old"}},
                ],
            },
            {"role": "assistant", "content": "I saw the image."},
        ]
        messages = runtime._build_initial_messages(
            system_prompt="System",
            user_message="Follow up question",
            initial_messages=initial,
        )
        assert len(messages) == 4  # system + 2 initial + 1 user
        # The first initial message should have list content preserved
        assert isinstance(messages[1]["content"], list)
        # The new user message is a string
        assert messages[-1]["content"] == "Follow up question"

    def test_switching_between_str_and_list_content(self):
        """Conversation with alternating str and list content types."""
        runtime = self._make_runtime()
        initial = [
            {"role": "user", "content": "plain text message"},
            {"role": "assistant", "content": "I understand."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "now with image"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,x"}},
                ],
            },
            {"role": "assistant", "content": "Nice image."},
        ]
        messages = runtime._build_initial_messages(
            system_prompt="System",
            user_message="final plain text",
            initial_messages=initial,
        )
        assert len(messages) == 6  # system + 4 initial + 1 user
        assert isinstance(messages[1]["content"], str)
        assert isinstance(messages[3]["content"], list)
        assert isinstance(messages[-1]["content"], str)

    def test_system_prompt_always_first(self):
        """System prompt must always be the first message."""
        runtime = self._make_runtime()
        initial = [
            {"role": "user", "content": "msg1"},
            {"role": "assistant", "content": "resp1"},
        ]
        content_blocks = [
            {"type": "text", "text": "multimodal msg"},
        ]
        messages = runtime._build_initial_messages(
            system_prompt="I am the system prompt",
            user_message=content_blocks,
            initial_messages=initial,
        )
        assert messages[0] == {"role": "system", "content": "I am the system prompt"}

    def test_empty_string_user_message_with_image_blocks(self):
        """Empty string user_message '' with list content still works."""
        runtime = self._make_runtime()
        # In practice, build_user_message would produce this from empty message + images
        content_blocks = [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
            {"type": "text", "text": ""},
        ]
        messages = runtime._build_initial_messages(
            system_prompt="System",
            user_message=content_blocks,
            initial_messages=None,
        )
        assert len(messages) == 2  # system + user
        assert messages[-1]["content"] == content_blocks

    def test_no_initial_messages_str_user(self):
        """No initial_messages + str user_message = just system + user."""
        runtime = self._make_runtime()
        messages = runtime._build_initial_messages(
            system_prompt="System",
            user_message="Hello",
            initial_messages=None,
        )
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1] == {"role": "user", "content": "Hello"}

    def test_empty_initial_messages_list(self):
        """Empty initial_messages list should behave like None."""
        runtime = self._make_runtime()
        messages = runtime._build_initial_messages(
            system_prompt="System",
            user_message="Hello",
            initial_messages=[],
        )
        # Empty list is falsy, so no initial messages appended
        assert len(messages) == 2

    def test_large_initial_messages_with_multimodal_user(self):
        """Many initial messages + multimodal user message."""
        runtime = self._make_runtime()
        initial = []
        for i in range(10):
            initial.append({"role": "user", "content": f"turn {i}"})
            initial.append({"role": "assistant", "content": f"reply {i}"})
        content_blocks = [
            {"type": "text", "text": "final question"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,xyz"}},
        ]
        messages = runtime._build_initial_messages(
            system_prompt="System",
            user_message=content_blocks,
            initial_messages=initial,
        )
        # system + 20 initial + 1 user = 22
        assert len(messages) == 22
        assert messages[-1]["content"] == content_blocks


# ============================================================
# 4. Gateway Material Processing Edge Cases
# ============================================================


class TestGatewayMaterialProcessing:
    """Edge cases for material processing in AgentGateway.chat().

    We test the material processing logic (mimetypes.guess_type behavior)
    in isolation since gateway.chat() has many dependencies.
    """

    def _simulate_material_processing(
        self, materials: list[dict], vision_enabled: bool = True
    ) -> tuple[list[str], list[dict]]:
        """
        Simulate the material processing logic from AgentGateway.chat()
        lines 247-263 without needing a full gateway instance.
        """
        text_summaries: list[str] = []
        image_blocks: list[dict] = []
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

    def test_uppercase_extension_png(self):
        """Filename with .PNG (uppercase) should still detect image/png."""
        summaries, blocks = self._simulate_material_processing([
            {"material_type": "image", "filename": "photo.PNG", "content": "base64data"},
        ])
        assert len(blocks) == 1
        assert blocks[0]["media_type"] == "image/png"

    def test_uppercase_extension_jpg(self):
        """Filename with .JPG should detect image/jpeg."""
        summaries, blocks = self._simulate_material_processing([
            {"material_type": "image", "filename": "photo.JPG", "content": "base64data"},
        ])
        assert len(blocks) == 1
        assert blocks[0]["media_type"] == "image/jpeg"

    def test_double_dots_in_filename(self):
        """Filename like photo.backup.png should detect based on last extension."""
        summaries, blocks = self._simulate_material_processing([
            {"material_type": "image", "filename": "photo.backup.png", "content": "data"},
        ])
        assert len(blocks) == 1
        assert blocks[0]["media_type"] == "image/png"

    def test_filename_with_spaces(self):
        """Filename with spaces should still detect mime type."""
        summaries, blocks = self._simulate_material_processing([
            {"material_type": "image", "filename": "my photo.png", "content": "data"},
        ])
        assert len(blocks) == 1
        assert blocks[0]["media_type"] == "image/png"

    def test_webp_format_detection(self):
        """WebP format should be detected by mimetypes."""
        summaries, blocks = self._simulate_material_processing([
            {"material_type": "image", "filename": "photo.webp", "content": "data"},
        ])
        assert len(blocks) == 1
        # mimetypes may or may not know webp; if not, falls back to image/png
        assert blocks[0]["media_type"] in ("image/webp", "image/png")

    def test_bmp_format_detection(self):
        """BMP format should be detected or fall back to image/png."""
        summaries, blocks = self._simulate_material_processing([
            {"material_type": "image", "filename": "photo.bmp", "content": "data"},
        ])
        assert len(blocks) == 1
        # mimetypes should know bmp on most systems
        assert blocks[0]["media_type"] in ("image/bmp", "image/x-ms-bmp", "image/png")

    def test_image_material_empty_content(self):
        """material_type=image but content is empty string -> text fallback."""
        summaries, blocks = self._simulate_material_processing([
            {"material_type": "image", "filename": "empty.png", "content": ""},
        ])
        # Empty content is falsy, so the `content and vision_enabled` check fails
        assert len(blocks) == 0
        assert len(summaries) == 1
        assert "[empty.png]" in summaries[0]

    def test_image_material_empty_bytes_as_string(self):
        """material_type=image but content is empty -> goes to text fallback."""
        summaries, blocks = self._simulate_material_processing([
            {"material_type": "image", "filename": "empty.png", "content": b""},
        ])
        # b"" is falsy
        assert len(blocks) == 0

    def test_vision_disabled_falls_back_to_text(self):
        """With vision disabled, image materials become text summaries."""
        summaries, blocks = self._simulate_material_processing(
            [
                {"material_type": "image", "filename": "photo.png", "content": "base64data"},
            ],
            vision_enabled=False,
        )
        assert len(blocks) == 0
        assert len(summaries) == 1
        assert "[photo.png]" in summaries[0]

    def test_no_filename_falls_back_to_image_png(self):
        """Empty filename should fall back to image/png."""
        summaries, blocks = self._simulate_material_processing([
            {"material_type": "image", "filename": "", "content": "data"},
        ])
        assert len(blocks) == 1
        assert blocks[0]["media_type"] == "image/png"

    def test_unknown_extension_falls_back(self):
        """Unknown file extension should fall back to image/png."""
        summaries, blocks = self._simulate_material_processing([
            {"material_type": "image", "filename": "photo.xyz123", "content": "data"},
        ])
        assert len(blocks) == 1
        # mimetypes won't know .xyz123, falls back to image/png
        assert blocks[0]["media_type"] == "image/png"

    def test_non_dict_material_skipped(self):
        """Non-dict materials should be skipped entirely."""
        summaries, blocks = self._simulate_material_processing([
            "not a dict",
            42,
            None,
        ])
        assert len(summaries) == 0
        assert len(blocks) == 0

    def test_material_missing_keys_uses_defaults(self):
        """Material dict with missing keys should use default values."""
        summaries, blocks = self._simulate_material_processing([
            {},
        ])
        # material_type defaults to "text", filename defaults to "", content to ""
        assert len(blocks) == 0
        assert len(summaries) == 1

    def test_mixed_image_and_text_materials(self):
        """Mix of image and text materials processed correctly."""
        summaries, blocks = self._simulate_material_processing([
            {"material_type": "image", "filename": "photo.png", "content": "imgdata"},
            {"material_type": "text", "filename": "doc.txt", "content": "text content"},
            {"material_type": "image", "filename": "chart.jpg", "content": "imgdata2"},
        ])
        assert len(blocks) == 2
        assert len(summaries) == 3
        assert blocks[0]["media_type"] == "image/png"
        assert blocks[1]["media_type"] == "image/jpeg"

    def test_jpeg_extension_variants(self):
        """Both .jpg and .jpeg should resolve to image/jpeg."""
        _, blocks_jpg = self._simulate_material_processing([
            {"material_type": "image", "filename": "a.jpg", "content": "d"},
        ])
        _, blocks_jpeg = self._simulate_material_processing([
            {"material_type": "image", "filename": "a.jpeg", "content": "d"},
        ])
        assert blocks_jpg[0]["media_type"] == "image/jpeg"
        assert blocks_jpeg[0]["media_type"] == "image/jpeg"

    def test_gif_format(self):
        """GIF format should be detected."""
        _, blocks = self._simulate_material_processing([
            {"material_type": "image", "filename": "anim.gif", "content": "d"},
        ])
        assert blocks[0]["media_type"] == "image/gif"

    def test_long_content_truncated_in_text_fallback(self):
        """Text content longer than 2000 chars gets truncated in summary."""
        long_content = "X" * 5000
        summaries, _ = self._simulate_material_processing([
            {"material_type": "text", "filename": "big.txt", "content": long_content},
        ])
        # content[:2000] means max 2000 chars of content in the summary
        assert len(summaries[0]) < 5100  # filename prefix + 2000 chars


# ============================================================
# 5. Additional TokenEstimator Cache Edge Cases
# ============================================================


class TestTokenEstimatorCacheBehavior:
    """Cache-specific edge cases for token estimator."""

    def setup_method(self):
        invalidate_cache()

    def test_invalidate_cache_resets(self):
        """After invalidate_cache(), next call should recalculate."""
        msg = {"role": "user", "content": "cache test"}
        first = _estimate_single_message_tokens(msg)
        invalidate_cache()
        second = _estimate_single_message_tokens(msg)
        assert first == second

    def test_different_roles_different_cache_keys(self):
        """Same content but different roles should produce different cache entries."""
        invalidate_cache()
        msg_user = {"role": "user", "content": "hello"}
        msg_system = {"role": "system", "content": "hello"}
        t1 = _estimate_single_message_tokens(msg_user)
        t2 = _estimate_single_message_tokens(msg_system)
        # Both should be same tokens (4 + text), but cached independently
        assert t1 == t2

    def test_tool_calls_in_cache_key(self):
        """Messages with tool_calls use a different cache key."""
        invalidate_cache()
        msg_without = {"role": "assistant", "content": "hello"}
        msg_with = {
            "role": "assistant",
            "content": "hello",
            "tool_calls": [{"function": {"name": "calc", "arguments": "{}"}}],
        }
        t1 = _estimate_single_message_tokens(msg_without)
        t2 = _estimate_single_message_tokens(msg_with)
        # With tool_calls should have more tokens
        assert t2 > t1


# ============================================================
# 6. PromptBuilder Edge Cases
# ============================================================


class TestPromptBuilderEdgeCases:
    """Additional PromptBuilder edge cases."""

    def setup_method(self):
        self.builder = PromptBuilder()

    def test_build_user_message_empty_message(self):
        """Empty message string without images returns just the empty string."""
        result = self.builder.build_user_message(message="")
        assert result == ""

    def test_build_user_message_empty_message_with_materials(self):
        """Empty message with materials summary should include materials."""
        result = self.builder.build_user_message(
            message="",
            materials_summary="some data",
        )
        assert "<materials>" in result
        assert "some data" in result

    def test_build_user_message_empty_image_blocks_list(self):
        """Empty list for image_blocks is falsy, should return str."""
        result = self.builder.build_user_message(
            message="test",
            image_blocks=[],
        )
        # Empty list is falsy, so not image_blocks -> str path
        assert isinstance(result, str)
        assert result == "test"

    def test_build_user_message_single_image_no_materials(self):
        """Single image, no materials -> 2 blocks (image + text)."""
        result = self.builder.build_user_message(
            message="describe",
            image_blocks=[{"base64": "abc", "media_type": "image/png"}],
        )
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["type"] == "image_url"
        assert result[1]["type"] == "text"
        assert result[1]["text"] == "describe"

    def test_build_user_message_unicode_in_base64(self):
        """Unicode characters in base64 field should be passed through."""
        result = self.builder.build_user_message(
            message="test",
            image_blocks=[{"base64": "data+with/special==chars", "media_type": "image/png"}],
        )
        img = [b for b in result if b["type"] == "image_url"][0]
        assert "data+with/special==chars" in img["image_url"]["url"]


# ============================================================
# 7. Gateway Image Compression Integration (A4-4i fix)
# ============================================================


class TestGatewayImageCompression:
    """Verify Gateway passes images through process_image() for compression."""

    def _make_png_bytes(self, width: int, height: int) -> bytes:
        """Create a minimal valid PNG with specific dimensions using PIL."""
        from PIL import Image
        img = Image.new("RGB", (width, height), color=(255, 0, 0))
        buf = __import__("io").BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def _run_gateway_material_logic(self, materials, vision_enabled=True):
        """Replicate the UPDATED gateway material processing logic with process_image."""
        from services.content_processor import process_image
        import base64 as b64mod

        text_summaries: list[str] = []
        image_blocks: list[dict] = []
        for m in (materials or []):
            if not isinstance(m, dict):
                continue
            mat_type = m.get("material_type", "text")
            filename = m.get("filename", "")
            content = m.get("content", "")

            if mat_type == "image" and content and vision_enabled:
                try:
                    raw_bytes = b64mod.b64decode(content)
                    processed = process_image(raw_bytes, filename)
                    image_blocks.append({
                        "base64": processed.image_base64,
                        "media_type": processed.image_media_type or "image/png",
                    })
                except Exception:
                    media_type = mimetypes.guess_type(filename)[0] or "image/png"
                    image_blocks.append({"base64": content, "media_type": media_type})
                text_summaries.append(f"[Image: {filename}]")
            else:
                text_summaries.append(f"[{filename}]\n{content[:2000]}")
        return text_summaries, image_blocks

    def test_small_image_not_resized(self):
        """Image smaller than 1024px should not be resized."""
        raw = self._make_png_bytes(200, 150)
        content_b64 = base64.b64encode(raw).decode()
        _, blocks = self._run_gateway_material_logic([
            {"material_type": "image", "filename": "small.png", "content": content_b64},
        ])
        assert len(blocks) == 1
        # Decode result and check dimensions unchanged
        from PIL import Image
        result_bytes = base64.b64decode(blocks[0]["base64"])
        img = Image.open(__import__("io").BytesIO(result_bytes))
        assert img.width == 200
        assert img.height == 150

    def test_large_image_compressed_to_1024(self):
        """Image larger than 1024px should be resized down."""
        raw = self._make_png_bytes(2048, 1536)
        content_b64 = base64.b64encode(raw).decode()
        _, blocks = self._run_gateway_material_logic([
            {"material_type": "image", "filename": "big.png", "content": content_b64},
        ])
        assert len(blocks) == 1
        from PIL import Image
        result_bytes = base64.b64decode(blocks[0]["base64"])
        img = Image.open(__import__("io").BytesIO(result_bytes))
        assert max(img.width, img.height) <= 1024

    def test_large_image_smaller_base64(self):
        """Compressed image should produce smaller base64 than original."""
        raw = self._make_png_bytes(3000, 2000)
        content_b64 = base64.b64encode(raw).decode()
        _, blocks = self._run_gateway_material_logic([
            {"material_type": "image", "filename": "huge.jpg", "content": content_b64},
        ])
        assert len(blocks) == 1
        # Compressed base64 should be shorter
        assert len(blocks[0]["base64"]) < len(content_b64)

    def test_invalid_base64_falls_back(self):
        """If base64 decode fails, gateway should fallback to raw content."""
        _, blocks = self._run_gateway_material_logic([
            {"material_type": "image", "filename": "bad.png", "content": "NOT_VALID_BASE64!!!"},
        ])
        assert len(blocks) == 1
        # Fallback: original content preserved
        assert blocks[0]["base64"] == "NOT_VALID_BASE64!!!"
        assert blocks[0]["media_type"] == "image/png"

    def test_corrupted_image_bytes_falls_back(self):
        """Valid base64 but not a real image — should fallback gracefully."""
        garbage = base64.b64encode(b"this is not an image").decode()
        _, blocks = self._run_gateway_material_logic([
            {"material_type": "image", "filename": "corrupt.png", "content": garbage},
        ])
        assert len(blocks) == 1
        # process_image handles corrupted bytes via except, still returns base64
        assert blocks[0]["base64"] is not None

    def test_jpeg_compression_used_for_jpg(self):
        """JPEG files should be re-saved as JPEG after resize."""
        raw = self._make_png_bytes(2000, 1500)  # create as PNG, but name it .jpg
        content_b64 = base64.b64encode(raw).decode()
        _, blocks = self._run_gateway_material_logic([
            {"material_type": "image", "filename": "photo.jpg", "content": content_b64},
        ])
        assert len(blocks) == 1
        assert blocks[0]["media_type"] == "image/jpeg"
