"""
Skill 质量验证器 — Phase 18。

在 Skill 创建/更新时自动验证格式、安全性和质量。

验证规则:
1. 必填字段 — name, description, type, version 必须存在
2. 类型验证 — type ∈ {domain, scenario, capability}
3. 内容长度 — body 在 50-5000 词范围
4. 依赖检查 — depends_on 中的 Skill 必须存在
5. 注入检测 — 检测 prompt injection 模式

Usage:
    validator = SkillValidator(existing_skill_names={"hospital-finance", "numeric-audit"})
    result = validator.validate(metadata, body)
    if result.status == "fail":
        print(result.errors)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class SkillValidationResult:
    """Skill 验证结果"""
    status: str = "pass"          # "pass" | "warning" | "fail"
    errors: list[str] = field(default_factory=list)     # 致命问题
    warnings: list[str] = field(default_factory=list)   # 非致命建议
    checks: dict[str, bool] = field(default_factory=dict)  # 各检查项结果


# Prompt injection 检测模式
_INJECTION_PATTERNS = [
    r"ignore\s+(previous|all|above|prior)\s+(instructions?|prompts?|rules?)",
    r"忽略(之前|上面|以上|所有)(的)?(指令|规则|提示|约束)",
    r"disregard\s+(previous|all|above)",
    r"you\s+are\s+now\s+a",
    r"你现在是",
    r"system\s*:\s*override",
    r"<\s*system\s*>",
    r"new\s+instructions?\s*:",
    r"jailbreak",
    r"DAN\s+mode",
]


class SkillValidator:
    """
    Skill 质量验证器。

    在 Skill 创建/更新/导入时执行验证规则，
    返回通过/警告/失败状态及详细信息。
    """

    REQUIRED_FIELDS = {"name", "description", "type", "version"}
    VALID_TYPES = {"domain", "scenario", "capability"}
    MIN_BODY_WORDS = 50
    MAX_BODY_WORDS = 5000

    def __init__(self, existing_skill_names: set[str] | None = None) -> None:
        self.existing_skills = existing_skill_names or set()

    def validate(self, metadata: dict, body: str) -> SkillValidationResult:
        """
        执行所有验证规则。

        Args:
            metadata: Skill 元数据 dict
            body: Skill 正文 (Markdown)

        Returns:
            SkillValidationResult
        """
        result = SkillValidationResult()

        checks = [
            self._check_required_fields,
            self._check_type_valid,
            self._check_body_length,
            self._check_dependencies,
            self._check_injection,
        ]

        for check in checks:
            check(metadata, body, result)

        # 有 error → fail, 有 warning → warning
        if result.errors:
            result.status = "fail"
        elif result.warnings:
            result.status = "warning"

        return result

    def _check_required_fields(
        self, metadata: dict, body: str, result: SkillValidationResult
    ) -> None:
        """检查必填字段。"""
        missing = self.REQUIRED_FIELDS - set(metadata.keys())
        # 也检查值为空的情况
        empty = {
            f for f in self.REQUIRED_FIELDS
            if f in metadata and not str(metadata.get(f, "")).strip()
        }
        all_missing = missing | empty

        if all_missing:
            result.errors.append(f"缺少必填字段: {', '.join(sorted(all_missing))}")
            result.checks["required_fields"] = False
        else:
            result.checks["required_fields"] = True

    def _check_type_valid(
        self, metadata: dict, body: str, result: SkillValidationResult
    ) -> None:
        """检查 type 是否有效。"""
        skill_type = metadata.get("type", "")
        if skill_type and skill_type not in self.VALID_TYPES:
            result.errors.append(
                f"无效的 type '{skill_type}', 必须是: {', '.join(sorted(self.VALID_TYPES))}"
            )
            result.checks["type_valid"] = False
        else:
            result.checks["type_valid"] = True

    def _check_body_length(
        self, metadata: dict, body: str, result: SkillValidationResult
    ) -> None:
        """检查正文长度。"""
        if not body or not body.strip():
            result.errors.append("Skill 正文为空")
            result.checks["body_length"] = False
            return

        # 中英混合词数估算: 中文按字符算, 英文按空格分词
        word_count = self._estimate_word_count(body)

        if word_count < self.MIN_BODY_WORDS:
            result.errors.append(
                f"正文过短 ({word_count} 词, 最少 {self.MIN_BODY_WORDS} 词)"
            )
            result.checks["body_length"] = False
        elif word_count > self.MAX_BODY_WORDS:
            result.warnings.append(
                f"正文较长 ({word_count} 词, 建议不超过 {self.MAX_BODY_WORDS} 词)"
            )
            result.checks["body_length"] = True  # 不阻塞
        else:
            result.checks["body_length"] = True

    def _check_dependencies(
        self, metadata: dict, body: str, result: SkillValidationResult
    ) -> None:
        """检查依赖是否存在。"""
        depends_on = metadata.get("depends_on", [])
        if not depends_on:
            result.checks["dependencies"] = True
            return

        missing_deps = [
            dep for dep in depends_on
            if dep not in self.existing_skills
        ]
        if missing_deps:
            result.warnings.append(
                f"依赖的 Skill 不存在: {', '.join(missing_deps)}"
            )
            result.checks["dependencies"] = False
        else:
            result.checks["dependencies"] = True

    def _check_injection(
        self, metadata: dict, body: str, result: SkillValidationResult
    ) -> None:
        """检测 prompt injection 模式。"""
        text = f"{metadata.get('name', '')} {metadata.get('description', '')} {body}"
        text_lower = text.lower()

        for pattern in _INJECTION_PATTERNS:
            if re.search(pattern, text_lower, re.IGNORECASE):
                result.errors.append(
                    f"检测到潜在 prompt injection 模式"
                )
                result.checks["injection_safe"] = False
                return

        result.checks["injection_safe"] = True

    def _estimate_word_count(self, text: str) -> int:
        """估算中英混合词数。"""
        # 移除 Markdown 标记
        clean = re.sub(r'[#*`\[\]()>|_-]', ' ', text)
        clean = re.sub(r'\s+', ' ', clean).strip()

        if not clean:
            return 0

        # 中文字符数 + 英文单词数
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', clean))
        # 移除中文后计算英文单词
        english_only = re.sub(r'[\u4e00-\u9fff]', ' ', clean)
        english_words = len(english_only.split())

        return chinese_chars + english_words
