"""
自验证与反思机制 — Phase 11。

Quality Gate: 在 Agent 产出 final_answer 前进行质量检查。
通过 agent_stop hook 实现自迭代 (Ralph Wiggum 模式):
- 检查表单完整性
- 检查审计结果一致性
- 检查数值计算是否使用了 calculator
- 不通过则 block + 返回修正提示让 Agent 继续迭代

Usage:
    hooks.register("agent_stop", quality_gate_hook)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from agent.hooks import HookEvent, HookResult

logger = logging.getLogger(__name__)

# 最大自迭代次数 (防止无限循环)
MAX_SELF_CORRECTIONS = 2


@dataclass
class QualityCheckResult:
    """质量检查结果。"""
    passed: bool = True
    issues: list[str] = field(default_factory=list)
    corrections: list[str] = field(default_factory=list)  # 注入给 Agent 的修正提示


class QualityGate:
    """
    Agent 输出质量门。

    在 agent_stop 事件中评估 Agent 的工具调用历史和最终输出，
    判断是否需要自迭代修正。
    """

    def __init__(
        self,
        checks: list[Callable[[HookEvent], tuple[bool, str, str]]] | None = None,
    ) -> None:
        self.checks = checks or [
            check_form_completeness,
            check_audit_consistency,
            check_calculation_verified,
        ]

    def evaluate(self, event: HookEvent) -> QualityCheckResult:
        """
        评估 Agent 输出质量。

        Args:
            event: agent_stop HookEvent (含 runtime_steps, context)

        Returns:
            QualityCheckResult
        """
        result = QualityCheckResult()

        for check_fn in self.checks:
            try:
                passed, issue, correction = check_fn(event)
                if not passed:
                    result.passed = False
                    result.issues.append(issue)
                    if correction:
                        result.corrections.append(correction)
            except Exception as e:
                logger.warning(f"Quality check {check_fn.__name__} error: {e}")
                # 检查函数出错不影响整体 → 视为通过
                continue

        return result


# ── 内置检查函数 ──


def check_form_completeness(event: HookEvent) -> tuple[bool, str, str]:
    """
    检查表单填写完整性。

    规则: 如果 business_context 中有 form_fields，
    则 runtime_steps 中的 update_form_field 调用应覆盖所有必填字段。
    """
    context = event.context or {}
    business_type = context.get("business_type", "")

    # 只在创建/起草场景下检查
    if not any(kw in business_type for kw in ("create", "draft")):
        return True, "", ""

    form_fields = context.get("form_fields", [])
    if not form_fields:
        return True, "", ""

    # 提取必填字段
    required_fields = set()
    for f in form_fields:
        if isinstance(f, dict):
            field_id = f.get("field_id") or f.get("id", "")
            if f.get("required", False) and field_id:
                required_fields.add(field_id)

    if not required_fields:
        return True, "", ""

    # 检查 runtime_steps 中哪些字段已填写
    filled_fields = set()
    steps = event.runtime_steps or []
    for step in steps:
        if isinstance(step, dict) and step.get("tool") == "update_form_field":
            args = step.get("args", {})
            field_id = args.get("field_id", "")
            if field_id:
                filled_fields.add(field_id)

    missing = required_fields - filled_fields
    if missing:
        issue = f"必填字段未填写: {', '.join(sorted(missing))}"
        correction = (
            f"请继续填写以下必填字段: {', '.join(sorted(missing))}。"
            "使用 update_form_field 工具逐一填写。"
        )
        return False, issue, correction

    return True, "", ""


def check_audit_consistency(event: HookEvent) -> tuple[bool, str, str]:
    """
    检查审计结果一致性。

    规则: 如果有 check_audit_rule 调用，检查是否有矛盾结论。
    """
    steps = event.runtime_steps or []

    audit_results = []
    for step in steps:
        if isinstance(step, dict) and step.get("tool") == "check_audit_rule":
            result = step.get("result", "")
            if isinstance(result, str):
                audit_results.append(result)

    if not audit_results:
        return True, "", ""

    # 简单一致性检查: 是否同时出现 "通过" 和 "不通过"
    has_pass = any("通过" in r and "不通过" not in r for r in audit_results)
    has_fail = any("不通过" in r for r in audit_results)

    # 如果有审计结果但没有调用 submit_all_audit_results
    has_submit = any(
        isinstance(step, dict) and step.get("tool") == "submit_all_audit_results"
        for step in steps
    )

    if audit_results and not has_submit:
        return (
            False,
            "审计检查完成但未提交汇总结果",
            "请使用 submit_all_audit_results 工具提交审计汇总结果。",
        )

    return True, "", ""


def check_calculation_verified(event: HookEvent) -> tuple[bool, str, str]:
    """
    检查数值计算是否使用了 calculator 工具。

    规则: 如果最终答案中包含数值比较 (> < = ≥ ≤)，
    检查 runtime_steps 是否使用了 calculator 系列工具。
    """
    context = event.context or {}
    final_answer = context.get("final_answer", "")

    # 检查最终答案中是否有数值比较/计算描述
    numeric_indicators = ["超出", "不足", "合计", "差额", "超标", "节余", "超过预算"]
    has_numeric = any(ind in final_answer for ind in numeric_indicators)

    if not has_numeric:
        return True, "", ""

    # 检查是否使用了 calculator 工具
    steps = event.runtime_steps or []
    calculator_tools = {"arithmetic", "numeric_compare", "sum_values",
                        "calculate_ratio", "date_diff"}
    used_calculator = any(
        isinstance(step, dict) and step.get("tool") in calculator_tools
        for step in steps
    )

    if not used_calculator:
        return (
            False,
            "最终答案包含数值比较但未使用 calculator 工具验证",
            "请使用 calculator 系列工具 (arithmetic/numeric_compare/sum_values) 验证数值计算结果的准确性。",
        )

    return True, "", ""


# ── Quality Gate Hook ──

# 用于追踪自迭代次数 (per-session)
_correction_counts: dict[str, int] = {}


def quality_gate_hook(event: HookEvent) -> HookResult:
    """
    agent_stop hook: 质量门。

    - 通过 → allow (Agent 正常结束)
    - 不通过 + 未超限 → block + 修正消息 (Agent 继续迭代)
    - 不通过 + 已超限 → allow (降级放行，避免无限循环)
    """
    # 安全清理: 防止模块级 dict 无限增长
    if len(_correction_counts) > 100:
        _correction_counts.clear()

    session_key = f"{event.user_id}:{event.session_id}"

    # 检查自迭代次数
    current_count = _correction_counts.get(session_key, 0)
    if current_count >= MAX_SELF_CORRECTIONS:
        logger.warning(
            f"Quality gate: max corrections ({MAX_SELF_CORRECTIONS}) reached, "
            f"allowing despite issues"
        )
        # 清理计数
        _correction_counts.pop(session_key, None)
        return HookResult(action="allow")

    gate = QualityGate()
    result = gate.evaluate(event)

    if result.passed:
        # 清理计数
        _correction_counts.pop(session_key, None)
        return HookResult(action="allow")

    # 不通过 → block + 修正提示
    _correction_counts[session_key] = current_count + 1

    correction_msg = (
        "[质量检查未通过]\n"
        "发现以下问题:\n"
        + "\n".join(f"- {issue}" for issue in result.issues)
        + "\n\n请进行以下修正:\n"
        + "\n".join(f"- {corr}" for corr in result.corrections)
    )

    logger.info(
        f"Quality gate blocked: {len(result.issues)} issues, "
        f"correction #{current_count + 1}/{MAX_SELF_CORRECTIONS}"
    )

    return HookResult(action="block", message=correction_msg)


def reset_correction_count(session_key: str) -> None:
    """重置自迭代计数 (用于测试或会话结束时清理)。"""
    _correction_counts.pop(session_key, None)
