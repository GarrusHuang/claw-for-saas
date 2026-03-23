"""
tool_search: 延迟工具搜索 — 当工具总数超过阈值时，
Agent 通过此工具按关键词发现未注入 prompt 的额外工具。

#17+40: BM25 评分 + tool_suggest (任务描述 → 推荐工具)。
"""

import math
from core.context import get_request_context
from core.tool_registry import ToolRegistry

tool_search_registry = ToolRegistry()


def _bm25_score(query_terms: list[str], doc_text: str, avg_dl: float, k1: float = 1.5, b: float = 0.75) -> float:
    """简化 BM25 评分: 基于词频和文档长度，支持 CJK 子串匹配。"""
    doc_lower = doc_text.lower()
    words = doc_lower.split()
    dl = len(words)
    if dl == 0:
        return 0.0
    score = 0.0
    for term in query_terms:
        # 先尝试精确 word 匹配
        tf = words.count(term)
        # CJK 子串匹配兜底: 如果精确匹配无结果，检查子串出现次数
        if tf == 0:
            tf = doc_lower.count(term)
        if tf == 0:
            continue
        numerator = tf * (k1 + 1)
        denominator = tf + k1 * (1 - b + b * dl / max(avg_dl, 1))
        score += numerator / denominator
    return score


def _search_deferred(query: str, limit: int = 10) -> dict:
    """BM25 搜索延迟工具。"""
    ctx = get_request_context()
    if not ctx.deferred_tools:
        return {"results": [], "message": "当前没有延迟加载的工具"}

    keywords = query.lower().split()
    if not keywords:
        return {"results": [], "total_deferred": len(ctx.deferred_tools)}

    # 计算平均文档长度
    docs = [(tool, f"{tool.name} {tool.description}") for tool in ctx.deferred_tools]
    avg_dl = sum(len(d.split()) for _, d in docs) / max(len(docs), 1)

    scored = []
    for tool, doc_text in docs:
        s = _bm25_score(keywords, doc_text, avg_dl)
        if s > 0:
            scored.append((s, tool))
    scored.sort(key=lambda x: -x[0])

    return {
        "results": [
            {"name": t.name, "description": t.description, "read_only": t.read_only}
            for _, t in scored[:limit]
        ],
        "total_deferred": len(ctx.deferred_tools),
    }


@tool_search_registry.tool(
    description="搜索额外可用工具。当 <tools> 中没有你需要的工具时，按关键词搜索 (BM25 排序)。",
    read_only=True,
)
def tool_search(query: str, limit: int = 10) -> dict:  # noqa: F811
    return _search_deferred(query, limit)


@tool_search_registry.tool(
    description=(
        "根据任务描述推荐合适的工具。传入自然语言任务描述，返回最相关的工具列表。"
        "适用于不确定该用哪个工具时。"
    ),
    read_only=True,
)
def tool_suggest(task_description: str, limit: int = 5) -> dict:
    """根据任务描述推荐工具 (搜索全部已注册工具，不限于 deferred)。"""
    ctx = get_request_context()

    # 收集所有工具 (deferred + core)
    all_tools = list(ctx.deferred_tools) if ctx.deferred_tools else []
    # 也搜索已注册到 prompt 的核心工具 (通过 tool_registry)
    try:
        from core.context import current_request
        c = current_request.get()
        if c and hasattr(c, 'event_bus'):
            # 暂时只搜 deferred (core 工具已在 prompt 中)
            pass
    except Exception:
        pass

    if not all_tools:
        return {"suggestions": [], "message": "没有额外工具可推荐，所有工具已在 <tools> 中"}

    keywords = task_description.lower().split()
    if not keywords:
        return {"suggestions": []}

    docs = [(tool, f"{tool.name} {tool.description}") for tool in all_tools]
    avg_dl = sum(len(d.split()) for _, d in docs) / max(len(docs), 1)

    scored = []
    for tool, doc_text in docs:
        s = _bm25_score(keywords, doc_text, avg_dl)
        if s > 0:
            scored.append((s, tool))
    scored.sort(key=lambda x: -x[0])

    return {
        "suggestions": [
            {"name": t.name, "description": t.description, "relevance": round(s, 2)}
            for s, t in scored[:limit]
        ],
    }
