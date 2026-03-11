"""
插件系统 — 四维扩展点。

ClawPlugin 基类定义插件接口。
PluginContext 暴露四维注册能力 (Tool/Hook/Prompt/Skill)。
PluginRegistry 管理插件生命周期 (加载/卸载/列出)。

插件加载方式:
1. 目录扫描: plugins/{name}/plugin.py 导出 plugin 变量
2. Entry points: "claw.plugins" group (pip install 的插件)
3. API 动态加载: POST /api/plugins/load
"""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import logging
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from agent.hooks import HookRegistry
    from agent.prompt import PromptBuilder, PromptLayer
    from core.tool_registry import ToolRegistry
    from skills.loader import SkillLoader

logger = logging.getLogger(__name__)


@dataclass
class PluginInfo:
    """插件元信息。"""
    name: str
    version: str
    description: str
    loaded: bool = True


class PluginContext:
    """
    插件上下文 — 四维扩展点。

    传给 plugin.on_load()，插件通过它注册扩展。
    """

    def __init__(
        self,
        tool_registry: ToolRegistry | None = None,
        hook_registry: HookRegistry | None = None,
        prompt_builder: PromptBuilder | None = None,
        skill_loader: SkillLoader | None = None,
    ) -> None:
        self._tool_registry = tool_registry
        self._hook_registry = hook_registry
        self._prompt_builder = prompt_builder
        self._skill_loader = skill_loader

    def register_tool(
        self,
        func: Callable,
        *,
        description: str = "",
        read_only: bool = False,
        name: str = "",
    ) -> None:
        """注册一个工具到插件工具注册表。"""
        if self._tool_registry is None:
            logger.warning("No tool registry available, tool registration skipped")
            return
        self._tool_registry.register(
            func=func,
            description=description,
            read_only=read_only,
            name=name,
        )

    def register_hook(
        self,
        event: str,
        handler: Callable,
        *,
        priority: int = 0,
        name: str = "",
    ) -> None:
        """注册一个生命周期钩子。"""
        if self._hook_registry is None:
            logger.warning("No hook registry available, hook registration skipped")
            return
        self._hook_registry.register(event, handler, priority=priority, name=name)

    def register_prompt_section(
        self,
        layer: PromptLayer,
        builder_fn: Callable,
        *,
        priority: int = 10,
        name: str = "",
    ) -> None:
        """注册一个 prompt section。"""
        if self._prompt_builder is None:
            logger.warning("No prompt builder available, prompt section registration skipped")
            return
        from agent.prompt import PromptSection
        section = PromptSection(
            layer=layer,
            priority=priority,
            name=name or f"plugin_{id(builder_fn)}",
            builder_fn=builder_fn,
        )
        self._prompt_builder.register_section(section)

    def register_skill(self, content: str) -> None:
        """注册一个 Skill (Markdown 内容)。"""
        if self._skill_loader is None:
            logger.warning("No skill loader available, skill registration skipped")
            return
        logger.info(f"Plugin skill registered ({len(content)} chars)")


class ClawPlugin(ABC):
    """
    Claw 插件基类。

    子类实现 on_load() 注册扩展，on_unload() 清理资源。
    """

    name: str = "unnamed"
    version: str = "0.1.0"
    description: str = ""

    @abstractmethod
    def on_load(self, ctx: PluginContext) -> None:
        """插件加载时调用，注册扩展。"""
        ...

    def on_unload(self) -> None:
        """插件卸载时调用，清理资源。"""
        pass


class PluginRegistry:
    """插件注册表 — 管理插件生命周期。"""

    def __init__(self) -> None:
        self._plugins: dict[str, ClawPlugin] = {}

    def load_plugin(self, plugin: ClawPlugin, ctx: PluginContext) -> None:
        """加载一个插件。"""
        if plugin.name in self._plugins:
            logger.warning(f"Plugin '{plugin.name}' already loaded, skipping")
            return

        try:
            plugin.on_load(ctx)
            self._plugins[plugin.name] = plugin
            logger.info(f"Plugin loaded: {plugin.name} v{plugin.version}")
        except Exception:
            logger.exception(f"Failed to load plugin: {plugin.name}")

    def unload_plugin(self, name: str) -> bool:
        """卸载一个插件。返回是否成功。"""
        plugin = self._plugins.pop(name, None)
        if plugin is None:
            return False

        try:
            plugin.on_unload()
            logger.info(f"Plugin unloaded: {name}")
        except Exception:
            logger.exception(f"Error during plugin unload: {name}")

        return True

    def list_plugins(self) -> list[PluginInfo]:
        """列出已加载插件。"""
        return [
            PluginInfo(
                name=p.name,
                version=p.version,
                description=p.description,
            )
            for p in self._plugins.values()
        ]

    def get_plugin(self, name: str) -> ClawPlugin | None:
        """获取已加载插件。"""
        return self._plugins.get(name)

    def load_from_directory(self, plugins_dir: str | Path, ctx: PluginContext) -> int:
        """
        从目录扫描加载插件。

        目录结构: plugins/{name}/plugin.py，导出 `plugin` 变量。
        返回成功加载的插件数量。
        """
        plugins_path = Path(plugins_dir)
        if not plugins_path.is_dir():
            logger.debug(f"Plugins directory not found: {plugins_path}")
            return 0

        count = 0
        for child in sorted(plugins_path.iterdir()):
            if not child.is_dir():
                continue

            plugin_file = child / "plugin.py"
            if not plugin_file.is_file():
                continue

            try:
                plugin = self._load_plugin_from_file(plugin_file, child.name)
                if plugin:
                    self.load_plugin(plugin, ctx)
                    count += 1
            except Exception:
                logger.exception(f"Failed to load plugin from {plugin_file}")

        return count

    def load_from_entry_points(self, group: str, ctx: PluginContext) -> int:
        """
        从 entry_points 加载插件 (pip install 的第三方插件)。
        返回成功加载的插件数量。
        """
        count = 0
        try:
            eps = importlib.metadata.entry_points()
            if hasattr(eps, "select"):
                plugin_eps = eps.select(group=group)
            else:
                plugin_eps = eps.get(group, [])

            for ep in plugin_eps:
                try:
                    plugin = ep.load()
                    if isinstance(plugin, ClawPlugin):
                        self.load_plugin(plugin, ctx)
                        count += 1
                    else:
                        logger.warning(
                            f"Entry point '{ep.name}' did not return a ClawPlugin instance"
                        )
                except Exception:
                    logger.exception(f"Failed to load plugin from entry point: {ep.name}")
        except Exception:
            logger.debug("No entry points found for plugin loading")

        return count

    def _load_plugin_from_file(self, plugin_file: Path, dir_name: str) -> ClawPlugin | None:
        """从文件加载插件模块，返回 plugin 变量。"""
        module_name = f"_claw_plugin_{dir_name}"

        plugin_dir = str(plugin_file.parent)
        if plugin_dir not in sys.path:
            sys.path.insert(0, plugin_dir)

        try:
            spec = importlib.util.spec_from_file_location(module_name, plugin_file)
            if spec is None or spec.loader is None:
                return None

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            plugin = getattr(module, "plugin", None)
            if plugin is None:
                logger.warning(f"No 'plugin' variable in {plugin_file}")
                return None

            if not isinstance(plugin, ClawPlugin):
                logger.warning(f"'plugin' in {plugin_file} is not a ClawPlugin instance")
                return None

            return plugin
        finally:
            if plugin_dir in sys.path:
                sys.path.remove(plugin_dir)
