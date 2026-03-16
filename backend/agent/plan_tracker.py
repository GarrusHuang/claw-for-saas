"""
PlanTracker — AI 主动驱动 plan step 推进。

工作流:
1. propose_plan 执行时创建 PlanTracker(steps, event_bus)
2. AI 在执行每个步骤前后主动调用 update_plan_step 工具
3. update_plan_step → PlanTracker.update_step(index, status) → 发射 SSE 事件
4. 步骤必须按顺序推进（不可跳步），错误时 fail_current() 标记当前步骤
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.event_bus import EventBus

logger = logging.getLogger(__name__)


class PlanTracker:
    """AI 主动驱动的 plan step 推进器。"""

    def __init__(self, steps: list[dict], event_bus: EventBus | None = None) -> None:
        self._steps = []
        for i, s in enumerate(steps):
            self._steps.append({
                "index": i,
                "action": s.get("action", ""),
                "description": s.get("description", ""),
                "status": "pending",
                "started_at": None,
                "completed_at": None,
            })
        self._event_bus = event_bus

    @property
    def steps(self) -> list[dict]:
        return list(self._steps)

    @property
    def current_index(self) -> int | None:
        for s in self._steps:
            if s["status"] == "running":
                return s["index"]
        return None

    def update_step(self, step_index: int, status: str) -> dict:
        """
        AI 主动更新步骤状态。

        Args:
            step_index: 步骤索引 (0-based)
            status: 目标状态 — "running" | "completed" | "failed"

        Returns:
            {"ok": True} 或 {"ok": False, "error": "..."}
        """
        if step_index < 0 or step_index >= len(self._steps):
            return {"ok": False, "error": f"step_index {step_index} 超出范围 (共 {len(self._steps)} 步)"}

        step = self._steps[step_index]
        now = time.time()

        if status == "running":
            # 前置步骤完成检查 — 拒绝跳步
            incomplete = [
                i for i in range(step_index)
                if self._steps[i]["status"] not in ("completed", "failed")
            ]
            if incomplete:
                statuses = {i: self._steps[i]["status"] for i in incomplete}
                return {
                    "ok": False,
                    "error": (
                        f"步骤 {step_index} 无法开始：前置步骤 {incomplete} 尚未完成 "
                        f"(状态: {statuses})，请先按顺序完成这些步骤"
                    ),
                }
            if step["status"] == "running":
                return {"ok": True}  # 已经在运行，幂等
            step["status"] = "running"
            step["started_at"] = now
            self._emit("step_started", {
                "step_index": step_index,
                "action": step["action"],
                "description": step["description"],
            })
            return {"ok": True}

        elif status == "completed":
            duration_ms = 0
            if step["started_at"]:
                duration_ms = round((now - step["started_at"]) * 1000)
            step["status"] = "completed"
            step["completed_at"] = now
            self._emit("step_completed", {
                "step_index": step_index,
                "action": step["action"],
                "duration_ms": duration_ms,
            })
            return {"ok": True}

        elif status == "failed":
            step["status"] = "failed"
            step["completed_at"] = now
            self._emit("step_failed", {
                "step_index": step_index,
                "action": step["action"],
            })
            return {"ok": True}

        else:
            return {"ok": False, "error": f"无效状态: {status}，支持 running/completed/failed"}

    def fail_current(self) -> None:
        """Pipeline 失败时标记当前运行中的步骤为 failed。"""
        current = self.current_index
        if current is not None:
            step = self._steps[current]
            step["status"] = "failed"
            step["completed_at"] = time.time()
            self._emit("step_failed", {
                "step_index": current,
                "action": step["action"],
            })

    def _emit(self, event_type: str, data: dict) -> None:
        if self._event_bus:
            self._event_bus.emit(event_type, data)
