"""
8 层系统提示构建器 — 对标 OpenClaw 8-layer prompt。

L1: Soul (prompts/soul.md) — 角色定义
L2: Skills Knowledge — SkillLoader 动态注入
L3: Business Context — domain data (XML)
L4: Memory Context — 用户偏好 + 经验
L5: Conversation History — (在 messages 中, 非 system prompt)
L6: Runtime Context — 时间戳、用户信息、会话ID
L7: Plan Mode — 当前模式 (plan/execute) + 约束
L8: User Message — (在 messages 中, 非 system prompt)
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# SOUL 文件路径
_SOUL_PATH = Path(__file__).parent.parent / "prompts" / "soul.md"


class PromptBuilder:
    """8 层系统提示构建器。"""

    def __init__(self, soul_path: Path | None = None) -> None:
        self._soul_path = soul_path or _SOUL_PATH
        self._soul_cache: str | None = None

    def _load_soul(self) -> str:
        """加载 SOUL 模板 (带缓存)。"""
        if self._soul_cache is None:
            try:
                self._soul_cache = self._soul_path.read_text(encoding="utf-8")
            except FileNotFoundError:
                logger.warning(f"Soul file not found: {self._soul_path}")
                self._soul_cache = "You are an AI assistant powered by Claw."
        return self._soul_cache

    def build_system_prompt(
        self,
        *,
        skill_knowledge: str = "",
        business_context: dict | None = None,
        memory_context: str = "",
        user_id: str = "anonymous",
        session_id: str = "",
        plan_mode: bool = True,
    ) -> str:
        """
        构建 L1-L7 系统提示。

        Args:
            skill_knowledge: L2 Skills 知识内容
            business_context: L3 业务参数 (form_fields, audit_rules, etc.)
            memory_context: L4 用户偏好 + 经验
            user_id: L6 用户 ID
            session_id: L6 会话 ID
            plan_mode: L7 模式 (True=AUTO自主模式, False=EXECUTE执行模式)
        """
        parts: list[str] = []

        # L1: Soul
        parts.append(self._load_soul())

        # L2: Skills Knowledge
        if skill_knowledge:
            parts.append(f"\n<skills>\n{skill_knowledge}\n</skills>")

        # L3: Business Context
        if business_context:
            parts.append(self._format_business_context(business_context))

        # L4: Memory Context
        if memory_context:
            parts.append(f"\n<memory>\n{memory_context}\n</memory>")

        # L6: Runtime Context
        parts.append(self._format_runtime_context(user_id, session_id))

        # L7: Mode Constraints
        parts.append(self._format_plan_mode(plan_mode))

        return "\n".join(parts)

    def build_user_message(
        self,
        *,
        message: str,
        materials_summary: str = "",
    ) -> str:
        """
        构建 L8 用户消息。

        Args:
            message: 用户原始消息
            materials_summary: 材料摘要
        """
        parts: list[str] = []

        if materials_summary:
            parts.append(f"<materials>\n{materials_summary}\n</materials>")

        parts.append(message)

        return "\n\n".join(parts)

    def _format_business_context(self, ctx: dict) -> str:
        """格式化业务上下文为 XML 标签。"""
        parts: list[str] = ["\n<business_context>"]

        # 候选类型
        if ctx.get("candidate_types"):
            parts.append("<candidate_types>")
            for ct in ctx["candidate_types"]:
                if isinstance(ct, dict):
                    parts.append(
                        f'  <type id="{ct.get("type_id", "")}" '
                        f'name="{ct.get("type_name", "")}" '
                        f'keywords="{",".join(ct.get("keywords", []))}" />'
                    )
            parts.append("</candidate_types>")

        # 表单字段
        if ctx.get("form_fields"):
            parts.append("<form_fields>")
            for ff in ctx["form_fields"]:
                if isinstance(ff, dict):
                    attrs = [
                        f'id="{ff.get("field_id", "")}"',
                        f'name="{ff.get("field_name", "")}"',
                        f'type="{ff.get("field_type", "text")}"',
                        f'required="{ff.get("required", True)}"',
                    ]
                    if ff.get("options"):
                        attrs.append(f'options="{",".join(ff["options"])}"')
                    if ff.get("description"):
                        attrs.append(f'description="{ff["description"]}"')
                    parts.append(f'  <field {" ".join(attrs)} />')
            parts.append("</form_fields>")

        # 审计规则
        if ctx.get("audit_rules"):
            parts.append("<audit_rules>")
            for ar in ctx["audit_rules"]:
                if isinstance(ar, dict):
                    parts.append(
                        f'  <rule id="{ar.get("rule_id", "")}" '
                        f'name="{ar.get("rule_name", "")}" '
                        f'severity="{ar.get("severity", "error")}" '
                        f'description="{ar.get("description", "")}" />'
                    )
            parts.append("</audit_rules>")

        # 已知值
        if ctx.get("known_values"):
            parts.append("<known_values>")
            for kv in ctx["known_values"]:
                if isinstance(kv, dict):
                    parts.append(
                        f'  <value field_id="{kv.get("field_id", "")}" '
                        f'value="{kv.get("value", "")}" '
                        f'source="{kv.get("source", "system")}" />'
                    )
            parts.append("</known_values>")

        parts.append("</business_context>")
        return "\n".join(parts)

    def _format_runtime_context(self, user_id: str, session_id: str) -> str:
        """格式化运行时上下文。"""
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        return (
            f"\n<runtime>\n"
            f"  <user_id>{user_id}</user_id>\n"
            f"  <session_id>{session_id}</session_id>\n"
            f"  <timestamp>{now}</timestamp>\n"
            f"</runtime>"
        )

    def _format_plan_mode(self, plan_mode: bool) -> str:
        """格式化模式约束。"""
        if plan_mode:
            # AUTO 模式: Agent 自主判断是否需要用户确认
            return (
                "\n<mode>AUTO</mode>\n"
                "<mode_constraints>\n"
                "你当前处于 **自主模式**。你拥有全部工具（含 propose_plan）。\n\n"
                "**自主判断规则：**\n"
                "根据 business_context 判断任务复杂度，决定工作方式：\n\n"
                "- **复杂任务**（同时包含 `<candidate_types>` 和 `<form_fields>`，如创建/起草）：\n"
                "  1. 先分析材料、查询必要数据\n"
                "  2. 调用 `propose_plan(requires_approval=True)` 提交方案\n"
                "  3. 输出方案要点总结后 **立即停止**，等待用户确认\n\n"
                "- **简单任务**（只有 `<audit_rules>` 或只有 `<form_fields>`，如审核/查询）：\n"
                "  1. 可选调用 `propose_plan(requires_approval=False)` 记录计划\n"
                "  2. 立即开始执行，不需要等待确认\n"
                "  3. 或直接跳过 propose_plan，直接调用能力工具\n\n"
                "**核心原则：**\n"
                "- propose_plan 的 requires_approval 参数决定是否需要用户确认\n"
                "- requires_approval=True 时：输出总结后必须停止\n"
                "- requires_approval=False 时：立即继续执行\n"
                "- 前端会实时显示计划进度，用户可以看到每一步的完成状态\n"
                "</mode_constraints>"
            )
        else:
            # EXECUTE 模式: 用户已确认方案，直接执行
            return (
                "\n<mode>EXECUTE</mode>\n"
                "<mode_constraints>\n"
                "你当前处于 **执行模式**。用户已确认你之前提出的方案。\n\n"
                "**工作流程：**\n"
                "1. 查看对话历史中你之前提出的方案\n"
                "2. 按方案依次调用能力工具完成各步骤\n"
                "3. 不要再调用 propose_plan（该工具在执行模式不可用）\n"
                "4. 所有步骤完成后输出最终总结\n"
                "</mode_constraints>"
            )
