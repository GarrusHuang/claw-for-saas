"""
插件管理 API。

GET  /api/plugins              — 列出已加载插件
POST /api/plugins/load         — 动态加载插件 (从 plugins/{name}/plugin.py)
POST /api/plugins/{name}/unload — 卸载插件
"""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from dependencies import get_plugin_registry, get_prompt_builder, get_skill_loader, get_settings

router = APIRouter(prefix="/api/plugins", tags=["plugins"])

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@router.get("")
async def list_plugins():
    """列出已加载插件。"""
    registry = get_plugin_registry()
    plugins = registry.list_plugins()
    return {
        "plugins": [
            {
                "name": p.name,
                "version": p.version,
                "description": p.description,
                "loaded": p.loaded,
            }
            for p in plugins
        ],
        "count": len(plugins),
    }


class LoadPluginRequest(BaseModel):
    """动态加载插件请求。"""
    name: str  # plugins/ 子目录名


@router.post("/load")
async def load_plugin(req: LoadPluginRequest):
    """
    动态加载插件。

    从 plugins/{name}/plugin.py 加载插件。
    如果插件已加载则返回 409。
    """
    from pathlib import Path
    from core.plugin import PluginContext
    from core.tool_registry import ToolRegistry

    registry = get_plugin_registry()

    # 检查是否已加载
    if registry.get_plugin(req.name):
        raise HTTPException(status_code=409, detail=f"Plugin '{req.name}' already loaded")

    # 定位插件文件
    s = get_settings()
    plugins_dir = Path(os.path.join(_BACKEND_ROOT, s.plugins_dir))
    plugin_dir = plugins_dir / req.name
    plugin_file = plugin_dir / "plugin.py"

    if not plugin_file.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"Plugin file not found: plugins/{req.name}/plugin.py",
        )

    # 加载插件模块
    plugin_obj = registry._load_plugin_from_file(plugin_file, req.name)
    if plugin_obj is None:
        raise HTTPException(
            status_code=400,
            detail=f"Plugin '{req.name}' has no valid 'plugin' variable",
        )

    # 构建插件上下文
    plugin_tool_registry: ToolRegistry | None = getattr(
        registry, "_plugin_tool_registry", None
    )
    if plugin_tool_registry is None:
        plugin_tool_registry = ToolRegistry()
        registry._plugin_tool_registry = plugin_tool_registry  # type: ignore[attr-defined]

    ctx = PluginContext(
        tool_registry=plugin_tool_registry,
        prompt_builder=get_prompt_builder(),
        skill_loader=get_skill_loader(),
    )

    # 加载
    registry.load_plugin(plugin_obj, ctx)

    # 确认加载成功
    if not registry.get_plugin(req.name):
        raise HTTPException(
            status_code=500,
            detail=f"Plugin '{req.name}' failed to load (check server logs)",
        )

    return {
        "message": f"Plugin '{req.name}' loaded",
        "name": plugin_obj.name,
        "version": plugin_obj.version,
        "description": plugin_obj.description,
    }


@router.post("/{name}/unload")
async def unload_plugin(name: str):
    """卸载指定插件。"""
    registry = get_plugin_registry()
    success = registry.unload_plugin(name)
    if not success:
        raise HTTPException(status_code=404, detail=f"Plugin '{name}' not found")
    return {"message": f"Plugin '{name}' unloaded", "name": name}
