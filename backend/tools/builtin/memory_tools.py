"""
记忆工具 (A8 重构) — Markdown 分层笔记。

Agent 可主动保存和查询记忆:
- save_memory: 写入 Markdown 笔记 (global/tenant/user 三级)
- recall_memory: 读取 Markdown 笔记
"""

from __future__ import annotations

import logging

from core.context import get_request_context
from core.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)

memory_capability_registry = ToolRegistry()


@memory_capability_registry.tool(
    description=(
        "保存记忆到 Markdown 笔记。"
        "当发现用户偏好、有效策略、重要规则、或需要跨会话记住的信息时使用。"
        "记忆按 scope 分层: user(个人) / tenant(团队) / global(全局)。"
        "默认保存到用户层 learning.md 文件。"
    ),
    read_only=False,
)
def save_memory(
    content: str,               # Markdown 格式的记忆内容
    scope: str = "user",        # "user" | "tenant" | "global"
    file: str = "learning.md",  # 目标文件名
    mode: str = "append",       # "append" 追加 | "rewrite" 覆盖
) -> dict:
    """保存记忆到 Markdown 笔记文件。"""
    ctx = get_request_context()
    store = ctx.memory_store
    if not store:
        return {"error": "MarkdownMemoryStore 未初始化"}

    tenant_id, user_id = ctx.tenant_id, ctx.user_id

    if scope not in ("user", "tenant", "global"):
        return {"error": f"无效的 scope: {scope}, 必须是 user/tenant/global"}

    # 兼容别名
    if mode == "overwrite":
        mode = "rewrite"
    if mode not in ("append", "rewrite"):
        return {"error": f"无效的 mode: {mode}, 必须是 append/rewrite"}

    try:
        ok = store.write_file(
            scope=scope,
            filename=file,
            content=content,
            mode=mode,
            tenant_id=tenant_id,
            user_id=user_id,
        )

        if not ok:
            return {"error": "写入失败"}

        # 检查是否需要压缩提示
        needs_compaction = store.file_needs_compaction(
            scope=scope, filename=file,
            tenant_id=tenant_id, user_id=user_id,
        )

        # 发射 SSE 事件
        bus = ctx.event_bus
        if bus:
            bus.emit("memory_saved", {
                "scope": scope,
                "file": file,
                "mode": mode,
            })

        result = {
            "status": "saved",
            "scope": scope,
            "file": file,
            "mode": mode,
        }
        if needs_compaction:
            result["hint"] = (
                f"文件 {file} 已超过大小阈值, 建议用 mode='rewrite' 重写精简内容。"
            )
        return result

    except Exception as e:
        logger.error(f"save_memory error: {e}")
        return {"error": str(e)}


@memory_capability_registry.tool(
    description=(
        "查询历史记忆。"
        "读取 Markdown 笔记文件, 返回全文内容。"
        "可按 scope 和文件名精确查询, 或读取某层级全部笔记。"
    ),
    read_only=True,
)
def recall_memory(
    scope: str = "user",       # "user" | "tenant" | "global" | "all"
    file: str = "",            # 指定文件名, 空 = 该层级全部
) -> dict:
    """查询 Markdown 笔记记忆。"""
    ctx = get_request_context()
    store = ctx.memory_store
    if not store:
        return {"error": "MarkdownMemoryStore 未初始化"}

    tenant_id, user_id = ctx.tenant_id, ctx.user_id

    try:
        if scope == "all":
            # 读取全部三级
            parts: list[str] = []
            for s in ("global", "tenant", "user"):
                content = store.read_all(s, tenant_id=tenant_id, user_id=user_id)
                if content:
                    parts.append(f"[{s}]\n{content}")
            return {
                "content": "\n\n".join(parts) if parts else "(无记忆)",
                "scope": "all",
            }

        if scope not in ("user", "tenant", "global"):
            return {"error": f"无效的 scope: {scope}"}

        if file:
            content = store.read_file(
                scope=scope, filename=file,
                tenant_id=tenant_id, user_id=user_id,
            )
            return {
                "content": content or "(文件为空或不存在)",
                "scope": scope,
                "file": file,
            }
        else:
            content = store.read_all(scope, tenant_id=tenant_id, user_id=user_id)
            files = store.list_files(scope, tenant_id=tenant_id, user_id=user_id)
            return {
                "content": content or "(无记忆)",
                "scope": scope,
                "files": files,
            }

    except Exception as e:
        logger.error(f"recall_memory error: {e}")
        return {"error": str(e)}


@memory_capability_registry.tool(
    description=(
        "按关键词搜索记忆。"
        "当 <memory> 标签中的概览不够详细时，用此工具按关键词搜索全部记忆文件。"
        "比 recall_memory 更精准 — 只返回包含关键词的段落，减少 token 消耗。"
    ),
    read_only=True,
)
def search_memory(
    query: str,                # 搜索关键词 (支持多个词，空格分隔，OR 匹配)
    scope: str = "user",       # "user" | "tenant" | "global" | "all"
) -> dict:
    """按关键词搜索记忆笔记，返回匹配的段落。"""
    ctx = get_request_context()
    store = ctx.memory_store
    if not store:
        return {"error": "MarkdownMemoryStore 未初始化"}

    tenant_id, user_id = ctx.tenant_id, ctx.user_id

    keywords = [k.strip().lower() for k in query.split() if k.strip()]
    if not keywords:
        return {"error": "请提供搜索关键词"}

    try:
        scopes = ["global", "tenant", "user"] if scope == "all" else [scope]
        matches: list[dict] = []

        for s in scopes:
            files = store.list_files(s, tenant_id=tenant_id, user_id=user_id)
            for fname in files:
                content = store.read_file(s, fname, tenant_id=tenant_id, user_id=user_id)
                if not content:
                    continue
                # 按段落搜索 (## 分割或双换行分割)
                paragraphs = content.split("\n## ")
                for i, para in enumerate(paragraphs):
                    para_lower = para.lower()
                    if any(kw in para_lower for kw in keywords):
                        prefix = "## " if i > 0 else ""
                        matches.append({
                            "scope": s,
                            "file": fname,
                            "content": (prefix + para)[:500],
                        })

        if not matches:
            return {"query": query, "matches": [], "message": "未找到匹配的记忆"}

        # 限制返回数量
        return {
            "query": query,
            "matches": matches[:10],
            "total": len(matches),
        }

    except Exception as e:
        logger.error(f"search_memory error: {e}")
        return {"error": str(e)}
