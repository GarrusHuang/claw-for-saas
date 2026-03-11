"""Tests for core/plugin.py — PluginRegistry, PluginContext, ClawPlugin."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.plugin import PluginRegistry, PluginContext, ClawPlugin


class DummyPlugin(ClawPlugin):
    name = "dummy"
    version = "0.1.0"
    description = "A dummy plugin for testing"

    def __init__(self):
        self.loaded = False
        self.unloaded = False

    def on_load(self, ctx: PluginContext) -> None:
        self.loaded = True

    def on_unload(self) -> None:
        self.unloaded = True


class AnotherPlugin(ClawPlugin):
    name = "another"
    version = "0.2.0"
    description = "Another test plugin"

    def on_load(self, ctx: PluginContext) -> None:
        pass


# ── PluginContext tests ──

def test_context_register_tool_no_registry():
    ctx = PluginContext()
    # Should not raise
    ctx.register_tool(lambda: None, description="test")


def test_context_register_hook_no_registry():
    ctx = PluginContext()
    ctx.register_hook("pre_tool_use", lambda e: None)


def test_context_register_prompt_section_no_registry():
    ctx = PluginContext()
    ctx.register_prompt_section(layer=None, builder_fn=lambda: "")


def test_context_register_skill_no_registry():
    ctx = PluginContext()
    ctx.register_skill("some content")


def test_context_with_tool_registry():
    """When tool_registry is provided, register_tool calls it."""
    calls = []

    class FakeRegistry:
        def register(self, **kwargs):
            calls.append(kwargs)

    ctx = PluginContext(tool_registry=FakeRegistry())
    ctx.register_tool(lambda: None, description="test", name="my_tool")
    assert len(calls) == 1
    assert calls[0]["name"] == "my_tool"


# ── PluginRegistry tests ──

def test_load_plugin_appears_in_list():
    reg = PluginRegistry()
    ctx = PluginContext()
    plugin = DummyPlugin()
    reg.load_plugin(plugin, ctx)
    plugins = reg.list_plugins()
    assert len(plugins) == 1
    assert plugins[0].name == "dummy"


def test_unload_plugin_removed():
    reg = PluginRegistry()
    ctx = PluginContext()
    plugin = DummyPlugin()
    reg.load_plugin(plugin, ctx)
    result = reg.unload_plugin("dummy")
    assert result is True
    assert len(reg.list_plugins()) == 0
    assert plugin.unloaded is True


def test_unload_unknown_returns_false():
    reg = PluginRegistry()
    assert reg.unload_plugin("nonexistent") is False


def test_get_plugin_returns_loaded():
    reg = PluginRegistry()
    ctx = PluginContext()
    plugin = DummyPlugin()
    reg.load_plugin(plugin, ctx)
    assert reg.get_plugin("dummy") is plugin


def test_load_from_empty_directory():
    reg = PluginRegistry()
    ctx = PluginContext()
    with tempfile.TemporaryDirectory() as tmpdir:
        count = reg.load_from_directory(tmpdir, ctx)
    assert count == 0


def test_load_from_nonexistent_directory():
    reg = PluginRegistry()
    ctx = PluginContext()
    count = reg.load_from_directory("/tmp/nonexistent_plugin_dir_xyz", ctx)
    assert count == 0


def test_duplicate_plugin_skipped():
    reg = PluginRegistry()
    ctx = PluginContext()
    p1 = DummyPlugin()
    p2 = DummyPlugin()
    reg.load_plugin(p1, ctx)
    reg.load_plugin(p2, ctx)
    assert len(reg.list_plugins()) == 1
    # p2 should not have been loaded
    assert p2.loaded is False
