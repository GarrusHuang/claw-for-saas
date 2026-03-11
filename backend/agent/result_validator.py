"""
工具结果验证器 — Phase 9。

验证工具返回结果的格式和合理性，
在结果不符合期望时发出警告。

Usage:
    validator = ToolResultValidator()
    valid, warning = validator.validate("classify_type", '{"type": "差旅报销"}')
    if not valid:
        print(warning)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ValidationRule:
    """工具结果验证规则"""
    must_contain: list[str] | None = None  # 结果中必须包含的关键词
    max_len: int = 5000  # 最大结果长度
    is_numeric: bool = False  # 结果是否应为数值


# 工具 → 验证规则
_VALIDATION_RULES: dict[str, ValidationRule] = {
    "classify_type": ValidationRule(
        must_contain=["type"],
        max_len=500,
    ),
    "update_form_field": ValidationRule(
        must_contain=["field_id"],
        max_len=200,
    ),
    "check_audit_rule": ValidationRule(
        must_contain=["rule_id"],
        max_len=1000,
    ),
    "submit_all_audit_results": ValidationRule(
        must_contain=["conclusion"],
        max_len=2000,
    ),
    "numeric_compare": ValidationRule(
        must_contain=["pass"],
        max_len=200,
    ),
    "sum_values": ValidationRule(
        is_numeric=True,
        max_len=100,
    ),
    "calculate_ratio": ValidationRule(
        is_numeric=True,
        max_len=100,
    ),
    "arithmetic": ValidationRule(
        max_len=200,
    ),
}


class ToolResultValidator:
    """
    验证工具返回结果的格式和合理性。

    非侵入式 — 只发出警告，不阻止执行。
    """

    def __init__(self, extra_rules: dict[str, ValidationRule] | None = None) -> None:
        self.rules = dict(_VALIDATION_RULES)
        if extra_rules:
            self.rules.update(extra_rules)

    def validate(self, tool_name: str, result: str) -> tuple[bool, str]:
        """
        验证工具结果。

        Args:
            tool_name: 工具名称
            result: 工具返回的字符串结果

        Returns:
            (valid, warning_message)
            valid=True 表示通过，warning_message 为空
            valid=False 表示有问题，warning_message 包含详情
        """
        rule = self.rules.get(tool_name)
        if rule is None:
            # 未知工具 → 默认通过
            return True, ""

        warnings: list[str] = []

        # 长度检查
        if len(result) > rule.max_len:
            warnings.append(
                f"结果过长 ({len(result)} > {rule.max_len})"
            )

        # 关键词检查
        if rule.must_contain:
            result_lower = result.lower()
            missing = [
                kw for kw in rule.must_contain
                if kw.lower() not in result_lower
            ]
            if missing:
                warnings.append(
                    f"缺少关键内容: {', '.join(missing)}"
                )

        # 数值检查
        if rule.is_numeric:
            try:
                # 尝试从结果中提取数值
                cleaned = result.strip().strip('"').strip("'")
                float(cleaned)
            except (ValueError, TypeError):
                # 可能是 JSON 格式，检查是否包含数值字段
                if not any(c.isdigit() for c in result):
                    warnings.append("期望数值结果但未找到数字")

        if warnings:
            msg = f"工具 {tool_name} 结果警告: {'; '.join(warnings)}"
            logger.warning(msg)
            return False, msg

        return True, ""

    def get_rule(self, tool_name: str) -> ValidationRule | None:
        """获取指定工具的验证规则。"""
        return self.rules.get(tool_name)
