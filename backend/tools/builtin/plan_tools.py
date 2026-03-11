"""
Plan 能力工具 — 双模式 (Plan Mode + Cowork)。

Agent 自主决定是否需要用户确认:
- requires_approval=True (Plan Mode): 提交方案后停止，等待用户确认
- requires_approval=False (Cowork): 提交方案后立即执行
"""

from __future__ import annotations

import json

from core.context import current_event_bus, current_plan_tracker
from core.tool_registry import ToolRegistry
from agent.plan_tracker import PlanTracker

plan_capability_registry = ToolRegistry()


@plan_capability_registry.tool(
    description=(
        "制定执行计划。分析完任务后，调用此工具记录执行计划。\n"
        "summary: 一句话概述 (显示在标题栏)。\n"
        "detail: 完整的 Markdown 格式计划文档，包含:\n"
        "  - 任务分析 (## 任务分析)\n"
        "  - 执行步骤 (## 执行步骤, 用 ### 分步, 列出每步的具体操作和涉及的工具)\n"
        "  - 预期结果 (## 预期结果)\n"
        "  用 Markdown 标题/列表/加粗等格式化，写出完整清晰的计划文档。\n"
        "steps: 执行步骤摘要列表，每个 step 必须包含 tools 字段:\n"
        "  [{'action': '推断单据类型', 'description': '...', 'tools': ['classify_type']}, ...]\n"
        "  tools 列出该步骤会调用的工具名 (用于自动进度追踪)。\n"
        "estimated_actions: 预计的工具调用次数。\n"
        "requires_approval 决定是否需要用户确认:\n"
        "  - True (Plan Mode): 复杂任务，提交方案后停止等待用户确认再执行\n"
        "  - False (Cowork): 简单任务，提交方案后立即开始执行\n"
        "调用后根据返回消息决定下一步行动。"
    ),
    read_only=False,
)
def propose_plan(
    summary: str,  # 一句话计划概述
    steps: list,  # 执行步骤摘要列表 [{"action": "...", "description": "..."}, ...]
    detail: str = "",  # 完整 Markdown 格式计划文档 (可选但强烈推荐)
    estimated_actions: int = 10,  # 预计工具调用次数
    requires_approval: bool = False,  # 是否需要用户确认
) -> dict:
    """记录执行计划并推送到前端进度面板。"""
    # LLM 可能把 steps 序列化成 JSON 字符串
    if isinstance(steps, str):
        try:
            steps = json.loads(steps)
        except (json.JSONDecodeError, TypeError):
            steps = []

    bus = current_event_bus.get()
    event_data = {
        "summary": summary,
        "detail": detail,
        "steps": steps,
        "estimated_actions": estimated_actions,
        "requires_approval": requires_approval,
    }
    if bus:
        bus.emit("plan_proposed", event_data)

    # 创建 PlanTracker 并存入 ContextVar (后端驱动步骤推进)
    tracker = PlanTracker(steps, event_bus=bus)
    current_plan_tracker.set(tracker)

    if requires_approval:
        return {
            "status": "awaiting_approval",
            "message": (
                "方案已提交给用户，等待确认。"
                "请输出一段简短的总结说明你的方案要点，然后停止。"
                "不要继续调用任何工具，用户确认后系统会自动开始执行。"
            ),
        }
    else:
        return {
            "status": "ok",
            "message": "计划已记录。请立即按计划开始执行，依次调用能力工具完成各步骤。",
        }
