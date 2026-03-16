"""
Plan 能力工具 — 进度展示 + AI 主动更新。

工作流:
1. AI 调用 propose_plan 制定计划 → 前端展示 todo list
2. AI 执行每个步骤前调用 update_plan_step(i, "running")
3. AI 完成每个步骤后调用 update_plan_step(i, "completed")
4. 前端实时更新步骤状态 (pending → running → completed)
"""

from __future__ import annotations

import json

from core.context import current_event_bus, current_plan_tracker
from core.tool_registry import ToolRegistry
from agent.plan_tracker import PlanTracker

plan_capability_registry = ToolRegistry()


@plan_capability_registry.tool(
    description=(
        "制定执行计划并向用户展示进度。分析完任务后，调用此工具记录执行计划。\n"
        "summary: 一句话概述 (显示在标题栏)。\n"
        "detail: 完整的 Markdown 格式计划文档，包含:\n"
        "  - 任务分析 (## 任务分析)\n"
        "  - 执行步骤 (## 执行步骤, 用 ### 分步, 列出每步的具体操作)\n"
        "  - 预期结果 (## 预期结果)\n"
        "  用 Markdown 标题/列表/加粗等格式化，写出完整清晰的计划文档。\n"
        "steps: 执行步骤摘要列表:\n"
        "  [{'action': '推断单据类型', 'description': '分析材料确定单据类型'}, ...]\n"
        "estimated_actions: 预计的工具调用次数。\n\n"
        "【重要】每个步骤必须严格遵循 running → 工作 → completed 的流程:\n"
        "  update_plan_step(step_index=N, status='running')    # 标记开始\n"
        "  ... 调用工具完成实际工作 ...\n"
        "  update_plan_step(step_index=N, status='completed')  # 标记完成\n"
        "  绝对不能跳过 completed。做完一步的工作后，必须立刻调 completed，然后再做任何其他事情。"
    ),
    read_only=False,
)
def propose_plan(
    summary: str,  # 一句话计划概述
    steps: list,  # 执行步骤摘要列表 [{"action": "...", "description": "..."}, ...]
    detail: str = "",  # 完整 Markdown 格式计划文档 (可选但强烈推荐)
    estimated_actions: int = 10,  # 预计工具调用次数
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
    }
    if bus:
        bus.emit("plan_proposed", event_data)

    # 创建 PlanTracker 并存入 ContextVar
    tracker = PlanTracker(steps, event_bus=bus)
    current_plan_tracker.set(tracker)

    step_count = len(steps)
    return {
        "status": "ok",
        "message": (
            f"计划已记录 (共 {step_count} 步)。请立即按计划开始执行。"
            "每步必须: running → 工作 → completed，绝对不能跳过 completed。"
        ),
    }


@plan_capability_registry.tool(
    description=(
        "更新执行计划中某个步骤的状态。\n"
        "step_index: 步骤索引 (从 0 开始)。\n"
        "status: 'running' (开始) | 'completed' (完成) | 'failed' (失败)\n\n"
        "【核心规则】每个步骤必须成对调用:\n"
        "  update_plan_step(step_index=N, status='running')    # 开始\n"
        "  ... 执行工作 ...\n"
        "  update_plan_step(step_index=N, status='completed')  # 完成\n"
        "做完一步的工作后，立刻调 completed，不能跳过。"
    ),
    read_only=False,
)
def update_plan_step(
    step_index: int,  # 步骤索引 (0-based)
    status: str,  # 目标状态: "running" | "completed" | "failed"
) -> dict:
    """更新计划步骤状态，推送实时进度到前端。"""
    tracker = current_plan_tracker.get(None)
    if tracker is None:
        return {"ok": False, "error": "尚未创建计划，请先调用 propose_plan"}

    result = tracker.update_step(step_index, status)

    # 每次 running 都提醒：做完工作后立即 complete
    if result.get("ok") and status == "running":
        result["reminder"] = (
            f"步骤 {step_index} 已开始。完成工作后必须立即调用 "
            f"update_plan_step(step_index={step_index}, status='completed')。"
        )

    return result
