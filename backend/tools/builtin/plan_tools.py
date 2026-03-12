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
        "【重要】调用 propose_plan 后，必须在执行每个步骤前后调用 update_plan_step 更新进度:\n"
        "  1. 开始步骤前: update_plan_step(step_index=0, status='running')\n"
        "  2. 完成步骤后: update_plan_step(step_index=0, status='completed')\n"
        "  3. 然后开始下一步: update_plan_step(step_index=1, status='running')\n"
        "  以此类推，确保用户能看到实时进度。"
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

    return {
        "status": "ok",
        "message": (
            "计划已记录。请立即按计划开始执行。"
            "执行每个步骤前后必须调用 update_plan_step 更新进度状态。"
        ),
    }


@plan_capability_registry.tool(
    description=(
        "更新执行计划中某个步骤的状态。在执行每个步骤前后必须调用此工具，"
        "让用户能看到实时进度。\n"
        "step_index: 步骤索引 (从 0 开始)。\n"
        "status: 目标状态:\n"
        "  - 'running': 开始执行此步骤 (步骤变为蓝色加载状态)\n"
        "  - 'completed': 此步骤已完成 (步骤变为绿色完成状态)\n"
        "  - 'failed': 此步骤执行失败 (步骤变为红色失败状态)\n\n"
        "典型用法:\n"
        "  update_plan_step(step_index=0, status='running')   # 开始第1步\n"
        "  ... 调用其他工具完成实际工作 ...\n"
        "  update_plan_step(step_index=0, status='completed') # 第1步完成\n"
        "  update_plan_step(step_index=1, status='running')   # 开始第2步"
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

    return tracker.update_step(step_index, status)
