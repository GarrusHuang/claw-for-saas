"""
tool_search: 延迟工具搜索 — 当工具总数超过阈值时，
Agent 通过此工具按关键词发现未注入 prompt 的额外工具。
"""

from core.context import get_request_context
from core.tool_registry import ToolRegistry

tool_search_registry = ToolRegistry()


@tool_search_registry.tool(
    description="搜索额外可用工具。当 <tools> 中没有你需要的工具时，按关键词搜索。",
    read_only=True,
)
def tool_search(query: str, limit: int = 10) -> dict:  # noqa: F811
    ctx = get_request_context()
    if not ctx.deferred_tools:
        return {"results": [], "message": "当前没有延迟加载的工具"}

    keywords = query.lower().split()
    results = []
    for tool in ctx.deferred_tools:
        text = f"{tool.name} {tool.description}".lower()
        score = sum(1 for kw in keywords if kw in text)
        if score > 0:
            results.append((score, tool))
    results.sort(key=lambda x: -x[0])

    return {
        "results": [
            {"name": t.name, "description": t.description, "read_only": t.read_only}
            for _, t in results[:limit]
        ],
        "total_deferred": len(ctx.deferred_tools),
    }
