"""Tests for agent/hooks.py — HookRegistry, built-in hooks."""
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.hooks import HookRegistry, HookEvent, HookResult, code_safety_hook


class TestHookRegistry:
    @pytest.mark.asyncio
    async def test_allow_by_default(self):
        reg = HookRegistry()
        result = await reg.fire(HookEvent(event_type="pre_tool_use", tool_name="calc"))
        assert result.action == "allow"

    @pytest.mark.asyncio
    async def test_block_takes_priority(self):
        reg = HookRegistry()

        def blocker(event):
            return HookResult(action="block", message="blocked!")

        def allower(event):
            return HookResult(action="allow")

        reg.register("pre_tool_use", allower)
        reg.register("pre_tool_use", blocker)

        result = await reg.fire(HookEvent(event_type="pre_tool_use"))
        assert result.action == "block"
        assert result.message == "blocked!"

    @pytest.mark.asyncio
    async def test_modify_result(self):
        reg = HookRegistry()

        def modifier(event):
            return HookResult(action="modify", modified_input={"new": "value"})

        reg.register("pre_tool_use", modifier)
        result = await reg.fire(HookEvent(event_type="pre_tool_use"))
        assert result.action == "modify"
        assert result.modified_input == {"new": "value"}

    @pytest.mark.asyncio
    async def test_matcher_filters(self):
        reg = HookRegistry()
        calls = []

        def handler(event):
            calls.append(event.tool_name)
            return HookResult(action="allow")

        reg.register("pre_tool_use", handler, matcher="specific_tool")

        # Should not trigger for different tool
        await reg.fire(HookEvent(event_type="pre_tool_use", tool_name="other_tool"))
        assert len(calls) == 0

        # Should trigger for matching tool
        await reg.fire(HookEvent(event_type="pre_tool_use", tool_name="specific_tool"))
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_async_handler(self):
        reg = HookRegistry()

        async def async_handler(event):
            return HookResult(action="block", message="async block")

        reg.register("pre_tool_use", async_handler)
        result = await reg.fire(HookEvent(event_type="pre_tool_use"))
        assert result.action == "block"

    @pytest.mark.asyncio
    async def test_handler_exception_is_caught(self):
        reg = HookRegistry()

        def bad_handler(event):
            raise RuntimeError("oops")

        reg.register("pre_tool_use", bad_handler)
        result = await reg.fire(HookEvent(event_type="pre_tool_use"))
        assert result.action == "allow"  # Falls through to default

    @pytest.mark.asyncio
    async def test_multiple_event_types(self):
        reg = HookRegistry()
        pre_calls = []
        post_calls = []

        reg.register("pre_tool_use", lambda e: (pre_calls.append(1), HookResult())[1])
        reg.register("post_tool_use", lambda e: (post_calls.append(1), HookResult())[1])

        await reg.fire(HookEvent(event_type="pre_tool_use"))
        assert len(pre_calls) == 1
        assert len(post_calls) == 0


class TestCodeSafetyHook:
    def test_allows_normal_tools(self):
        event = HookEvent(event_type="pre_tool_use", tool_name="calculator", tool_input={})
        result = code_safety_hook(event)
        assert result.action == "allow"

    def test_blocks_sensitive_file_write(self):
        event = HookEvent(
            event_type="pre_tool_use",
            tool_name="write_source_file",
            tool_input={"path": "/app/.env"},
        )
        result = code_safety_hook(event)
        assert result.action == "block"
        assert "敏感文件" in result.message

    def test_blocks_credentials_write(self):
        event = HookEvent(
            event_type="pre_tool_use",
            tool_name="write_source_file",
            tool_input={"path": "/home/user/credentials.json"},
        )
        result = code_safety_hook(event)
        assert result.action == "block"

    def test_blocks_private_key_write(self):
        event = HookEvent(
            event_type="pre_tool_use",
            tool_name="write_source_file",
            tool_input={"path": "/root/.ssh/id_rsa"},
        )
        result = code_safety_hook(event)
        assert result.action == "block"

    def test_blocks_rm_rf_command(self):
        event = HookEvent(
            event_type="pre_tool_use",
            tool_name="run_command",
            tool_input={"command": "rm -rf /"},
        )
        result = code_safety_hook(event)
        assert result.action == "block"

    def test_blocks_sudo_command(self):
        event = HookEvent(
            event_type="pre_tool_use",
            tool_name="run_command",
            tool_input={"command": "sudo apt install foo"},
        )
        result = code_safety_hook(event)
        assert result.action == "block"

    def test_blocks_fork_bomb(self):
        event = HookEvent(
            event_type="pre_tool_use",
            tool_name="run_command",
            tool_input={"command": ":() { :|:& };:"},
        )
        result = code_safety_hook(event)
        assert result.action == "block"

    def test_allows_safe_command(self):
        event = HookEvent(
            event_type="pre_tool_use",
            tool_name="run_command",
            tool_input={"command": "ls -la"},
        )
        result = code_safety_hook(event)
        assert result.action == "allow"

    def test_allows_normal_file_write(self):
        event = HookEvent(
            event_type="pre_tool_use",
            tool_name="write_source_file",
            tool_input={"path": "/app/src/main.py"},
        )
        result = code_safety_hook(event)
        assert result.action == "allow"

    def test_allows_read_source_file(self):
        event = HookEvent(
            event_type="pre_tool_use",
            tool_name="read_source_file",
            tool_input={"path": "/app/.env"},
        )
        # read_source_file doesn't block sensitive files (only write does)
        result = code_safety_hook(event)
        assert result.action == "allow"
