"""
LearningMemory: Layer 4 — 两阶段长期学习记忆。

从 agent-engine 的 Platform Memory 借鉴，积累跨会话的成功模式。

Phase 1: 经验收集 (Experience Collection)
  - Pipeline 完成后，若用户确认结果（无修正或少量修正），记录为成功经验
  - 提取工具调用序列、Skill 组合、输出质量分

Phase 2: 经验应用 (Experience Application)
  - 新任务进入时，查询同类场景的历史成功经验
  - 将经验摘要注入 Agent 的 system prompt
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any

logger = logging.getLogger(__name__)

# 默认持久化路径
_DEFAULT_STORAGE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "learning_memory.json",
)


@dataclass
class LearningExperience:
    """学习经验记录。"""

    experience_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    category: str = ""                    # "audit_pattern" | "form_fill_strategy" | "type_inference"
    business_type: str = ""               # 报销 / 合同
    scenario: str = ""                    # reimbursement_create 等
    doc_type: str = ""                    # 差旅报销 / 采购合同 等
    description: str = ""                 # 经验描述
    context_summary: str = ""             # 触发上下文摘要
    success_pattern: dict[str, Any] = field(default_factory=dict)  # 成功模式数据
    confidence: float = 0.5              # 0.0-1.0，随成功次数增长
    created_at: float = field(default_factory=time.time)
    last_used: float = 0.0
    use_count: int = 0


class LearningMemory:
    """
    两阶段长期学习记忆管理器。

    Phase 1: 经验收集
    - record_success(): Pipeline 完成后记录成功经验
    - 自动提取工具调用链、关键决策点

    Phase 2: 经验应用
    - get_relevant_experiences(): 查询同类场景经验
    - build_experience_prompt(): 构建注入 prompt 的经验文本

    持久化: JSON（Demo 模式）
    """

    def __init__(self, storage_path: str | None = None) -> None:
        self.storage_path = storage_path or _DEFAULT_STORAGE_PATH
        self._experiences: list[LearningExperience] = []
        self._load()

    # ─────────────────────────────────────────────────────────────
    # Phase 1: 经验收集
    # ─────────────────────────────────────────────────────────────

    def record_success(
        self,
        scenario: str,
        business_type: str,
        doc_type: str = "",
        category: str = "",
        description: str = "",
        context_summary: str = "",
        success_pattern: dict[str, Any] | None = None,
        correction_count: int = 0,
    ) -> LearningExperience:
        """
        记录一次成功经验。

        Args:
            scenario: 场景名称
            business_type: 业务类型
            doc_type: 单据类型
            category: 经验类别
            description: 经验描述
            context_summary: 上下文摘要
            success_pattern: 成功模式数据（工具链、参数等）
            correction_count: 用户修正次数（修正越少 confidence 越高）

        Returns:
            创建的 LearningExperience
        """
        # 计算初始置信度：无修正 = 0.9，少量修正 = 0.6-0.8
        if correction_count == 0:
            initial_confidence = 0.9
        elif correction_count <= 2:
            initial_confidence = 0.7
        else:
            initial_confidence = 0.5

        # 查找是否已有类似经验（相同场景+业务类型+类别）
        existing = self._find_similar(scenario, business_type, category, doc_type)

        if existing:
            # 更新已有经验
            existing.use_count += 1
            existing.last_used = time.time()
            # 置信度随成功次数增长（上限 0.99）
            existing.confidence = min(0.99, existing.confidence + 0.05)
            if description:
                existing.description = description  # 用最新的描述
            if success_pattern:
                existing.success_pattern = success_pattern

            logger.info(
                f"Experience updated: {existing.experience_id}, "
                f"confidence={existing.confidence:.2f}, "
                f"use_count={existing.use_count}"
            )
            self._save()
            return existing

        # 创建新经验
        experience = LearningExperience(
            category=category or self._infer_category(scenario),
            business_type=business_type,
            scenario=scenario,
            doc_type=doc_type,
            description=description,
            context_summary=context_summary,
            success_pattern=success_pattern or {},
            confidence=initial_confidence,
        )
        self._experiences.append(experience)

        logger.info(
            f"New experience recorded: {experience.experience_id}, "
            f"scenario={scenario}, confidence={initial_confidence}"
        )
        self._save()
        return experience

    # ─────────────────────────────────────────────────────────────
    # Phase 2: 经验应用
    # ─────────────────────────────────────────────────────────────

    def get_relevant_experiences(
        self,
        scenario: str,
        business_type: str,
        doc_type: str = "",
        top_k: int = 3,
    ) -> list[LearningExperience]:
        """
        查询同类场景的相关经验。

        匹配优先级：
        1. 完全匹配（scenario + business_type + doc_type）
        2. 场景+业务类型匹配
        3. 业务类型匹配

        按 confidence 降序排列，返回 top_k 条。
        """
        # 精确匹配
        exact_matches = [
            e for e in self._experiences
            if e.scenario == scenario
            and e.business_type == business_type
            and (not doc_type or e.doc_type == doc_type)
        ]

        if len(exact_matches) >= top_k:
            exact_matches.sort(key=lambda e: e.confidence, reverse=True)
            return exact_matches[:top_k]

        # 场景+业务类型匹配
        scenario_matches = [
            e for e in self._experiences
            if e.scenario == scenario
            and e.business_type == business_type
            and e not in exact_matches
        ]

        # 仅业务类型匹配
        type_matches = [
            e for e in self._experiences
            if e.business_type == business_type
            and e not in exact_matches
            and e not in scenario_matches
        ]

        # 合并、排序、截取
        all_matches = exact_matches + scenario_matches + type_matches
        all_matches.sort(key=lambda e: e.confidence, reverse=True)

        return all_matches[:top_k]

    def build_experience_prompt(
        self,
        scenario: str,
        business_type: str,
        doc_type: str = "",
    ) -> str:
        """
        构建经验注入 prompt。

        格式示例：
        基于历史成功案例的建议:
        1. 差旅报销审计中，先调用 get_user_profile 获取职级，
           再用 get_expense_standards 查标准，最后用 calculator 比较，
           成功率 95%（12次）
        2. 合同审核中，重点关注付款条款和违约金条款

        Args:
            scenario: 场景名称
            business_type: 业务类型
            doc_type: 单据类型

        Returns:
            经验提示文本，无匹配时返回空字符串
        """
        experiences = self.get_relevant_experiences(
            scenario, business_type, doc_type, top_k=3
        )

        if not experiences:
            return ""

        lines: list[str] = ["基于历史成功案例的建议:"]

        for i, exp in enumerate(experiences, 1):
            confidence_pct = f"{exp.confidence * 100:.0f}%"
            count_str = f"（{exp.use_count}次）" if exp.use_count > 0 else ""

            line = f"{i}. "
            if exp.description:
                line += f"{exp.description}"
            else:
                line += f"{exp.doc_type or exp.business_type}场景"

            line += f"，成功率 {confidence_pct}{count_str}"

            # 如果有成功模式中的工具链信息
            tool_chain = exp.success_pattern.get("tool_chain", [])
            if tool_chain:
                tools_str = " → ".join(tool_chain[:5])
                line += f"\n   推荐工具链: {tools_str}"

            lines.append(line)

        return "\n".join(lines)

    # ─────────────────────────────────────────────────────────────
    # 经验整合（维护）
    # ─────────────────────────────────────────────────────────────

    def consolidate(self, max_experiences: int = 100) -> int:
        """
        经验整合：合并相似经验，淘汰低价值经验。

        规则：
        1. 淘汰 confidence < 0.3 且超过 60 天未使用的经验
        2. 如果总数超过 max_experiences，淘汰最低 confidence 的
        3. 合并完全相同 category+scenario+business_type 的经验

        Returns:
            被淘汰的经验数
        """
        before = len(self._experiences)

        # 规则 1: 淘汰低价值过期经验
        threshold_time = time.time() - (60 * 86400)  # 60 天前
        self._experiences = [
            e for e in self._experiences
            if not (e.confidence < 0.3 and (e.last_used if e.last_used > 0 else getattr(e, 'created_at', 0)) < threshold_time)
        ]

        # 规则 2: 总数限制
        if len(self._experiences) > max_experiences:
            self._experiences.sort(key=lambda e: e.confidence, reverse=True)
            self._experiences = self._experiences[:max_experiences]

        removed = before - len(self._experiences)
        if removed > 0:
            logger.info(f"Consolidated: removed {removed} experiences, remaining {len(self._experiences)}")
            self._save()

        return removed

    # ─────────────────────────────────────────────────────────────
    # 统计
    # ─────────────────────────────────────────────────────────────

    @property
    def total_experiences(self) -> int:
        """总经验数。"""
        return len(self._experiences)

    def get_stats(self) -> dict[str, Any]:
        """返回统计信息。"""
        if not self._experiences:
            return {"total": 0, "scenarios": 0, "avg_confidence": 0.0}

        scenarios = set(e.scenario for e in self._experiences)
        avg_confidence = sum(e.confidence for e in self._experiences) / len(self._experiences)

        return {
            "total": len(self._experiences),
            "scenarios": len(scenarios),
            "avg_confidence": round(avg_confidence, 2),
            "total_uses": sum(e.use_count for e in self._experiences),
        }

    # ─────────────────────────────────────────────────────────────
    # 内部方法
    # ─────────────────────────────────────────────────────────────

    def _find_similar(
        self,
        scenario: str,
        business_type: str,
        category: str,
        doc_type: str,
    ) -> LearningExperience | None:
        """查找类似经验。"""
        for e in self._experiences:
            if (
                e.scenario == scenario
                and e.business_type == business_type
                and e.category == category
                and e.doc_type == doc_type
            ):
                return e
        return None

    def _infer_category(self, scenario: str) -> str:
        """从场景名推断类别。"""
        if "audit" in scenario or "review" in scenario:
            return "audit_pattern"
        elif "form" in scenario or "create" in scenario or "draft" in scenario:
            return "form_fill_strategy"
        elif "inference" in scenario:
            return "type_inference"
        return "general"

    def _load(self) -> None:
        """从 JSON 文件加载。"""
        if not os.path.exists(self.storage_path):
            return

        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            for item in data.get("experiences", []):
                exp = LearningExperience(
                    experience_id=item.get("experience_id", uuid.uuid4().hex[:12]),
                    category=item.get("category", ""),
                    business_type=item.get("business_type", ""),
                    scenario=item.get("scenario", ""),
                    doc_type=item.get("doc_type", ""),
                    description=item.get("description", ""),
                    context_summary=item.get("context_summary", ""),
                    success_pattern=item.get("success_pattern", {}),
                    confidence=item.get("confidence", 0.5),
                    created_at=item.get("created_at", time.time()),
                    last_used=item.get("last_used", 0.0),
                    use_count=item.get("use_count", 0),
                )
                self._experiences.append(exp)

            logger.info(f"Loaded {len(self._experiences)} learning experiences")

        except (json.JSONDecodeError, KeyError, OSError) as e:
            logger.warning(f"Failed to load learning memory: {e}")

    def _save(self) -> None:
        """保存到 JSON 文件。"""
        try:
            os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)

            data = {
                "experiences": [asdict(e) for e in self._experiences],
                "version": "1.0",
            }

            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

        except OSError as e:
            logger.error(f"Failed to save learning memory: {e}")

    def clear(self) -> None:
        """清空所有经验（仅清内存）。"""
        self._experiences.clear()
        logger.info("LearningMemory cleared")
