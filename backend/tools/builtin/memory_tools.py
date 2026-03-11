"""
记忆能力工具。

Agent 可主动保存学习经验和查询历史经验。
- save_memory: 保存经验到 LearningMemory (长期记忆)
- recall_memory: 查询同类场景的历史经验
"""

from __future__ import annotations

import logging

from core.context import current_event_bus, current_learning_memory
from core.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)

memory_capability_registry = ToolRegistry()


@memory_capability_registry.tool(
    description=(
        "保存学习经验到长期记忆。"
        "当发现用户偏好模式、有效工具调用策略、或重要业务规则时使用。"
        "经验会跨会话持久化，在后续同类任务中自动注入。"
    ),
    read_only=False,
)
def save_memory(
    description: str,            # 经验描述
    category: str = "",          # audit_pattern | form_fill_strategy | general
    context_summary: str = "",   # 触发上下文摘要
) -> dict:
    """保存一条学习经验到长期记忆。"""
    lm = current_learning_memory.get(None)
    if not lm:
        return {"error": "LearningMemory 未初始化"}

    scenario = "unknown"
    business_type = "unknown"
    doc_type = ""

    try:
        exp = lm.record_success(
            scenario=scenario,
            business_type=business_type,
            doc_type=doc_type,
            category=category,
            description=description,
            context_summary=context_summary,
            success_pattern={},
            correction_count=0,
        )

        # 发射 SSE 事件
        bus = current_event_bus.get(None)
        if bus:
            bus.emit("memory_saved", {
                "experience_id": exp.experience_id,
                "description": description,
                "category": category or "general",
                "confidence": exp.confidence,
            })

        return {
            "status": "saved",
            "experience_id": exp.experience_id,
            "confidence": exp.confidence,
        }

    except Exception as e:
        logger.error(f"save_memory error: {e}")
        return {"error": str(e)}


@memory_capability_registry.tool(
    description=(
        "查询历史学习经验。"
        "处理新任务前，可回顾同类场景的历史经验和成功策略。"
        "返回按置信度排序的经验列表。"
    ),
    read_only=True,
)
def recall_memory(
    scenario: str = "",        # 场景 (如 reimbursement_create)
    business_type: str = "",   # 业务类型 (如 reimbursement)
    top_k: int = 3,            # 返回数量
) -> dict:
    """查询同类场景的历史学习经验。"""
    lm = current_learning_memory.get(None)
    if not lm:
        return {"error": "LearningMemory 未初始化"}

    if not scenario and not business_type:
        scenario = ""
        business_type = ""

    try:
        experiences = lm.get_relevant_experiences(
            scenario=scenario,
            business_type=business_type,
            top_k=top_k,
        )

        items = []
        for exp in experiences:
            items.append({
                "experience_id": exp.experience_id,
                "category": exp.category,
                "description": exp.description,
                "confidence": exp.confidence,
                "use_count": exp.use_count,
                "success_pattern": exp.success_pattern,
            })

        return {
            "experiences": items,
            "total": len(items),
        }

    except Exception as e:
        logger.error(f"recall_memory error: {e}")
        return {"error": str(e)}
