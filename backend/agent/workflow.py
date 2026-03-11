"""
Agent 工作流状态追踪 — Phase 9。

根据工具调用推断当前阶段，提供进度估算。

Usage:
    tracker = WorkflowTracker()
    tracker.on_tool_call("classify_type")   # → CLASSIFYING
    tracker.on_tool_call("update_form_field") # → FORM_FILLING
    print(tracker.estimate_progress())       # → 0.4
"""

from __future__ import annotations

import logging
from enum import Enum

logger = logging.getLogger(__name__)


class WorkflowPhase(str, Enum):
    """工作流阶段枚举"""
    INITIALIZING = "initializing"     # 加载上下文
    CLASSIFYING = "classifying"       # 类型推断
    FORM_FILLING = "form_filling"     # 表单填写
    AUDITING = "auditing"             # 审计检查
    REVIEWING = "reviewing"           # 审查验证
    GENERATING = "generating"         # 文档生成
    COMPLETING = "completing"         # 完成收尾


# 工具 → 阶段映射
_TOOL_PHASE_MAP: dict[str, WorkflowPhase] = {
    "classify_type": WorkflowPhase.CLASSIFYING,
    "update_form_field": WorkflowPhase.FORM_FILLING,
    "check_audit_rule": WorkflowPhase.AUDITING,
    "submit_all_audit_results": WorkflowPhase.AUDITING,
    "generate_document": WorkflowPhase.GENERATING,
    "spawn_subagent": WorkflowPhase.REVIEWING,
    "parallel_review": WorkflowPhase.REVIEWING,
}

# 阶段排序 (用于进度估算)
_PHASE_ORDER = [
    WorkflowPhase.INITIALIZING,
    WorkflowPhase.CLASSIFYING,
    WorkflowPhase.FORM_FILLING,
    WorkflowPhase.AUDITING,
    WorkflowPhase.REVIEWING,
    WorkflowPhase.GENERATING,
    WorkflowPhase.COMPLETING,
]

# 业务类型 → 典型阶段数
_BUSINESS_PHASE_COUNT: dict[str, int] = {
    "reimbursement_create": 5,  # 推断 → 填表 → 审计 → 生成 → 完成
    "reimbursement_review": 3,  # 审计 → 审查 → 完成
    "contract_draft": 4,        # 推断 → 填表 → 生成 → 完成
    "contract_review": 3,       # 审计 → 审查 → 完成
}


class WorkflowTracker:
    """
    工作流状态追踪器。

    根据工具调用推断当前阶段，维护阶段历史，
    并基于业务类型估算完成进度。
    """

    def __init__(self, business_type: str = "") -> None:
        self.current_phase = WorkflowPhase.INITIALIZING
        self.completed_phases: list[WorkflowPhase] = []
        self.tool_history: list[str] = []
        self.business_type = business_type

    def on_tool_call(self, tool_name: str) -> WorkflowPhase:
        """
        根据工具调用更新阶段。

        Args:
            tool_name: 被调用的工具名称

        Returns:
            当前阶段
        """
        self.tool_history.append(tool_name)

        new_phase = _TOOL_PHASE_MAP.get(tool_name)
        if new_phase and new_phase != self.current_phase:
            # 记录阶段切换
            if self.current_phase not in self.completed_phases:
                self.completed_phases.append(self.current_phase)
            self.current_phase = new_phase
            logger.debug(
                f"Workflow phase: {self.current_phase.value} "
                f"(after tool: {tool_name})"
            )

        return self.current_phase

    def estimate_progress(self) -> float:
        """
        估算完成百分比。

        Returns:
            0.0 ~ 1.0 之间的浮点数
        """
        total_phases = _BUSINESS_PHASE_COUNT.get(self.business_type, 5)
        completed = len(self.completed_phases)

        # 当前阶段算 0.5 个
        progress = (completed + 0.5) / total_phases
        return min(max(progress, 0.0), 1.0)

    def mark_completed(self) -> None:
        """标记整个工作流完成。"""
        if self.current_phase not in self.completed_phases:
            self.completed_phases.append(self.current_phase)
        self.current_phase = WorkflowPhase.COMPLETING

    def to_dict(self) -> dict:
        """序列化为 dict (用于 SSE 事件)。"""
        return {
            "phase": self.current_phase.value,
            "completed_phases": [p.value for p in self.completed_phases],
            "progress": round(self.estimate_progress(), 2),
            "tool_count": len(self.tool_history),
        }
