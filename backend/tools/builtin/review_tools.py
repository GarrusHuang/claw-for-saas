"""
并行审查工具 — Phase 13。

主 Agent 通过 parallel_review 工具启动多 Agent 并行审查。

实际执行由 ParallelReviewOrchestrator 完成（通过 contextvars 注入）。
"""

from __future__ import annotations

import contextvars
import json
from typing import Any

from core.tool_registry import ToolRegistry

review_capability_registry = ToolRegistry()

# ParallelReviewOrchestrator 注入 (由 Gateway 设置)
_review_orchestrator: contextvars.ContextVar[Any] = contextvars.ContextVar(
    "_review_orchestrator", default=None
)


@review_capability_registry.tool(
    description=(
        "启动多 Agent 并行审查。"
        "多个专业化 Agent 从不同角度审查同一份文档/报销单/合同。"
        "content: 待审查的内容文本。"
        "agent_roles: 参与审查的角色列表 (如 ['data-validator', 'compliance-reviewer'])。"
        "可用角色: data-validator(数据验证), compliance-reviewer(合规审查), document-reviewer(文档审查)。"
        "context: 附加业务上下文 (可选)。"
        "返回汇总的审查结果，包含整体结论和各 Agent 的详细意见。"
    ),
    read_only=False,
)
async def parallel_review(
    content: str,        # 待审查的内容
    agent_roles: str,    # 角色列表 (逗号分隔, 如 "data-validator,compliance-reviewer")
    context: str = "",   # 附加上下文
) -> str:
    """启动多 Agent 并行审查，返回汇总结果。"""
    orchestrator = _review_orchestrator.get()
    if orchestrator is None:
        return "错误: ParallelReviewOrchestrator 未初始化。请确认系统已正确配置并行审查功能。"

    # 解析角色列表 (支持逗号分隔和 JSON 数组)
    roles = _parse_roles(agent_roles)
    if not roles:
        return "错误: 未指定审查角色。请提供至少一个角色 (如 'data-validator,compliance-reviewer')。"

    result = await orchestrator.parallel_review(
        content=content,
        agent_roles=roles,
        context=context,
    )

    # 格式化输出
    output_parts = [
        f"## 并行审查完成",
        f"",
        f"**整体结论**: {result.overall_status}",
        f"**整体信心**: {result.overall_confidence}%",
        f"**耗时**: {result.duration_ms:.0f}ms",
        f"**参与 Agent**: {len(result.individual_results)} 个",
        f"",
        f"### 各 Agent 审查详情",
    ]

    for r in result.individual_results:
        output_parts.append(f"")
        output_parts.append(f"#### {r.agent_role}")
        output_parts.append(f"- 结论: {r.conclusion}")
        output_parts.append(f"- 信心: {r.confidence}%")
        output_parts.append(f"- 耗时: {r.duration_ms:.0f}ms")
        if r.details:
            # 截取详情前 500 字
            details_preview = r.details[:500]
            if len(r.details) > 500:
                details_preview += "..."
            output_parts.append(f"- 详情: {details_preview}")

    return "\n".join(output_parts)


def _parse_roles(agent_roles: str) -> list[str]:
    """解析角色列表字符串。"""
    # 尝试 JSON 数组
    try:
        parsed = json.loads(agent_roles)
        if isinstance(parsed, list):
            return [str(r).strip() for r in parsed if str(r).strip()]
    except (json.JSONDecodeError, TypeError):
        pass

    # 逗号分隔
    roles = [r.strip() for r in agent_roles.split(",") if r.strip()]
    return roles
