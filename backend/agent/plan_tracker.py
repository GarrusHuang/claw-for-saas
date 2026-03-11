"""
PlanTracker — 后端驱动 plan step 推进。

通过 Agent 在 propose_plan 中提供的 tools 字段，
机械匹配工具执行 → 步骤推进，零业务逻辑。

工作流:
1. propose_plan 执行时创建 PlanTracker(steps, event_bus)
2. 每次工具执行后调用 on_tool_executed(tool_name)
3. PlanTracker 在 steps[i].tools 中查找匹配:
   - 匹配到新 step → 发射 step_completed(当前) + step_started(新)
   - 匹配到当前 step → 无操作
   - 无匹配 → 无操作 (优雅降级)
4. pipeline 结束时调用 complete_all() 标记剩余步骤完成
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.event_bus import EventBus

logger = logging.getLogger(__name__)


class PlanTracker:
    """后端驱动的 plan step 推进器。"""

    def __init__(self, steps: list[dict], event_bus: EventBus | None = None) -> None:
        """
        Args:
            steps: plan steps, 每个 step 至少有 action/description,
                   可选 tools: list[str] 用于匹配。
            event_bus: SSE 事件总线。
        """
        self._steps = []
        for i, s in enumerate(steps):
            tools = s.get("tools") or []
            if isinstance(tools, str):
                tools = [tools]
            self._steps.append({
                "index": i,
                "action": s.get("action", ""),
                "description": s.get("description", ""),
                "tools": [t.strip() for t in tools if t],
                "status": "pending",
                "started_at": None,
                "completed_at": None,
            })
        self._event_bus = event_bus
        self._current_index: int | None = None

    @property
    def steps(self) -> list[dict]:
        return list(self._steps)

    @property
    def current_index(self) -> int | None:
        return self._current_index

    def on_tool_executed(self, tool_name: str, success: bool = True) -> None:
        """
        工具执行后调用。向前搜索匹配 step。

        匹配策略:
        1. 从当前步骤开始向后搜索 (含当前)
        2. 匹配到当前 step → 无操作
        3. 匹配到后续 step → 完成当前, 启动新 step
        4. 无匹配 → 无操作 (优雅降级)
        """
        if not self._steps:
            return

        matched_index = self._find_matching_step(tool_name)
        if matched_index is None:
            return

        # 匹配到当前正在运行的 step → 无操作
        if matched_index == self._current_index:
            return

        now = time.time()

        # 完成当前正在运行的 step
        if self._current_index is not None:
            current = self._steps[self._current_index]
            if current["status"] == "running":
                current["status"] = "completed"
                current["completed_at"] = now
                duration_ms = 0
                if current["started_at"]:
                    duration_ms = round((now - current["started_at"]) * 1000)
                self._emit("step_completed", {
                    "step_index": self._current_index,
                    "action": current["action"],
                    "duration_ms": duration_ms,
                })

        # 完成当前和新 step 之间的所有 pending 步骤 (跳步场景)
        start = (self._current_index or 0) + 1 if self._current_index is not None else 0
        for i in range(start, matched_index):
            step = self._steps[i]
            if step["status"] == "pending":
                step["status"] = "completed"
                step["completed_at"] = now
                self._emit("step_completed", {
                    "step_index": i,
                    "action": step["action"],
                    "duration_ms": 0,
                })

        # 启动新 step
        new_step = self._steps[matched_index]
        new_step["status"] = "running"
        new_step["started_at"] = now
        self._current_index = matched_index
        self._emit("step_started", {
            "step_index": matched_index,
            "action": new_step["action"],
            "description": new_step["description"],
        })

    def complete_all(self) -> None:
        """Pipeline 完成时标记所有剩余步骤为 completed。"""
        now = time.time()
        for i, step in enumerate(self._steps):
            if step["status"] in ("pending", "running"):
                duration_ms = 0
                if step["status"] == "running" and step["started_at"]:
                    duration_ms = round((now - step["started_at"]) * 1000)
                step["status"] = "completed"
                step["completed_at"] = now
                self._emit("step_completed", {
                    "step_index": i,
                    "action": step["action"],
                    "duration_ms": duration_ms,
                })

    def fail_current(self) -> None:
        """Pipeline 失败时标记当前步骤为 failed。"""
        if self._current_index is not None:
            step = self._steps[self._current_index]
            if step["status"] == "running":
                step["status"] = "failed"
                step["completed_at"] = time.time()
                self._emit("step_failed", {
                    "step_index": self._current_index,
                    "action": step["action"],
                })

    def _find_matching_step(self, tool_name: str) -> int | None:
        """
        从当前位置向后搜索匹配 tool_name 的 step。

        优先匹配当前及后续步骤，不回溯已完成步骤。
        """
        search_start = self._current_index if self._current_index is not None else 0
        for i in range(search_start, len(self._steps)):
            if tool_name in self._steps[i]["tools"]:
                return i
        return None

    def _emit(self, event_type: str, data: dict) -> None:
        if self._event_bus:
            self._event_bus.emit(event_type, data)
