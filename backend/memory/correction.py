"""
CorrectionMemory: Layer 3 — 用户修正记忆。

记录用户对 Agent 输出的修正，下次同类场景优先采用。
核心逻辑：
1. 记录修正（用户将 Agent 的值 A 改为值 B）
2. 查询修正历史（按用户+业务类型+字段匹配）
3. 构建偏好提示注入 UniversalFormAgent 的 user_message
4. 衰减机制：超过 90 天未被采用的修正记录降低优先级
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Any

logger = logging.getLogger(__name__)

# 默认持久化路径
_DEFAULT_STORAGE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "correction_memory.json",
)

# 衰减阈值（秒）
_DECAY_THRESHOLD_DAYS = 90
_DECAY_THRESHOLD_SECONDS = _DECAY_THRESHOLD_DAYS * 86400


@dataclass
class CorrectionRecord:
    """用户修正记录。"""

    user_id: str
    business_type: str                    # 报销 / 合同
    doc_type: str                         # 差旅报销 / 采购合同 等
    field_id: str                         # 被修正的字段 ID
    agent_value: str                      # Agent 原始填写值
    user_value: str                       # 用户修正后的值
    context_snapshot: dict[str, Any] = field(default_factory=dict)  # 修正时上下文
    created_at: float = field(default_factory=time.time)
    last_applied: float = 0.0            # 最近被采用的时间
    times_applied: int = 0               # 后续被采用的次数


class CorrectionMemory:
    """
    用户修正记忆管理器。

    持久化到 JSON 文件（Demo 模式）。
    生产环境应替换为数据库存储。

    集成方式：
    - Orchestrator 在调用 UniversalFormAgent 前查询修正历史
    - 构建偏好提示注入到 params["user_preferences"]
    - UniversalFormAgent._build_user_message 将其作为参考信息
    """

    def __init__(self, storage_path: str | None = None) -> None:
        self.storage_path = storage_path or _DEFAULT_STORAGE_PATH
        self._records: list[CorrectionRecord] = []
        self._load()

    # ─────────────────────────────────────────────────────────────
    # 记录管理
    # ─────────────────────────────────────────────────────────────

    def record_correction(
        self,
        user_id: str,
        business_type: str,
        doc_type: str,
        field_id: str,
        agent_value: str,
        user_value: str,
        context_snapshot: dict[str, Any] | None = None,
    ) -> CorrectionRecord:
        """
        记录用户修正。

        如果同一用户对同一字段已有修正记录且 user_value 相同，
        则增加 times_applied 计数而非创建新记录。
        """
        # 查找是否已有相同修正
        existing = self._find_existing(user_id, business_type, doc_type, field_id, user_value)

        if existing:
            existing.times_applied += 1
            existing.last_applied = time.time()
            existing.context_snapshot = context_snapshot or existing.context_snapshot
            logger.info(
                f"Correction updated: user={user_id}, field={field_id}, "
                f"value='{user_value}', times={existing.times_applied}"
            )
            self._save()
            return existing

        record = CorrectionRecord(
            user_id=user_id,
            business_type=business_type,
            doc_type=doc_type,
            field_id=field_id,
            agent_value=agent_value,
            user_value=user_value,
            context_snapshot=context_snapshot or {},
        )
        self._records.append(record)

        logger.info(
            f"Correction recorded: user={user_id}, field={field_id}, "
            f"'{agent_value}' → '{user_value}'"
        )
        self._save()
        return record

    def get_corrections(
        self,
        user_id: str,
        business_type: str,
        doc_type: str | None = None,
        field_id: str | None = None,
    ) -> list[CorrectionRecord]:
        """
        查询修正历史。

        按用户、业务类型匹配，可选按单据类型和字段 ID 进一步过滤。
        结果按优先级排序：times_applied 越多、created_at 越新越靠前。
        """
        matches: list[CorrectionRecord] = []

        for record in self._records:
            if record.user_id != user_id:
                continue
            if record.business_type != business_type:
                continue
            if doc_type and record.doc_type != doc_type:
                continue
            if field_id and record.field_id != field_id:
                continue
            matches.append(record)

        # 按优先级排序：times_applied 降序，created_at 降序
        matches.sort(key=lambda r: (r.times_applied, r.created_at), reverse=True)

        return matches

    def mark_applied(self, record: CorrectionRecord) -> None:
        """标记某条修正记录被采用。"""
        record.times_applied += 1
        record.last_applied = time.time()
        self._save()

    # ─────────────────────────────────────────────────────────────
    # 偏好注入
    # ─────────────────────────────────────────────────────────────

    def build_preference_prompt(
        self,
        user_id: str,
        business_type: str,
        doc_type: str,
        field_ids: list[str] | None = None,
    ) -> str:
        """
        构建用户偏好提示，注入到 UniversalFormAgent。

        格式示例：
        <user_preferences>
        用户在之前的差旅报销中：
        - 将"meal_subsidy"从 Agent 推断的"80元/天"修正为"100元/天"（共3次）
        - 将"transport_type"从"火车"修正为"高铁"（共2次）
        请优先参考用户偏好。
        </user_preferences>

        Args:
            user_id: 用户 ID
            business_type: 业务类型
            doc_type: 单据类型
            field_ids: 可选，只匹配指定字段

        Returns:
            偏好提示文本，无匹配时返回空字符串
        """
        corrections = self.get_corrections(user_id, business_type, doc_type)

        if not corrections:
            return ""

        # 如果指定了 field_ids，进一步过滤
        if field_ids:
            corrections = [c for c in corrections if c.field_id in field_ids]

        if not corrections:
            return ""

        # 过滤衰减记录（超过 90 天未采用且 times_applied < 3）
        now = time.time()
        active_corrections = []
        for c in corrections:
            last_active = c.last_applied if c.last_applied > 0 else c.created_at
            age = now - last_active
            if age > _DECAY_THRESHOLD_SECONDS and c.times_applied < 3:
                continue  # 衰减：老旧且不常用的记录跳过
            active_corrections.append(c)

        if not active_corrections:
            return ""

        # 构建偏好提示
        lines: list[str] = []
        lines.append(f"用户在之前的{doc_type}中：")

        for c in active_corrections[:5]:  # 最多展示 5 条
            times_str = f"（共{c.times_applied}次）" if c.times_applied > 1 else ""
            lines.append(
                f"- 将「{c.field_id}」从 Agent 推断的「{c.agent_value}」"
                f"修正为「{c.user_value}」{times_str}"
            )

        lines.append("请优先参考用户偏好。")

        return "\n".join(lines)

    # ─────────────────────────────────────────────────────────────
    # 统计与清理
    # ─────────────────────────────────────────────────────────────

    @property
    def total_records(self) -> int:
        """总记录数。"""
        return len(self._records)

    def get_stats(self) -> dict[str, Any]:
        """返回统计信息。"""
        if not self._records:
            return {"total": 0, "users": 0, "fields": 0}

        users = set(r.user_id for r in self._records)
        fields = set(r.field_id for r in self._records)
        avg_times = sum(r.times_applied for r in self._records) / len(self._records)

        return {
            "total": len(self._records),
            "users": len(users),
            "fields": len(fields),
            "avg_times_applied": round(avg_times, 1),
        }

    def cleanup_stale(self, max_age_days: int = 180) -> int:
        """
        清理过期记录。

        删除超过 max_age_days 天且 times_applied == 0 的记录。

        Returns:
            被清理的记录数
        """
        threshold = time.time() - (max_age_days * 86400)
        before = len(self._records)

        self._records = [
            r for r in self._records
            if not (r.created_at < threshold and r.times_applied == 0)
        ]

        removed = before - len(self._records)
        if removed > 0:
            logger.info(f"Cleaned up {removed} stale correction records")
            self._save()

        return removed

    # ─────────────────────────────────────────────────────────────
    # 内部持久化
    # ─────────────────────────────────────────────────────────────

    def _find_existing(
        self,
        user_id: str,
        business_type: str,
        doc_type: str,
        field_id: str,
        user_value: str,
    ) -> CorrectionRecord | None:
        """查找已有相同修正记录。"""
        for r in self._records:
            if (
                r.user_id == user_id
                and r.business_type == business_type
                and r.doc_type == doc_type
                and r.field_id == field_id
                and r.user_value == user_value
            ):
                return r
        return None

    def _load(self) -> None:
        """从 JSON 文件加载记录。"""
        if not os.path.exists(self.storage_path):
            logger.info(f"No existing correction memory at {self.storage_path}")
            return

        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            for item in data.get("records", []):
                record = CorrectionRecord(
                    user_id=item["user_id"],
                    business_type=item["business_type"],
                    doc_type=item["doc_type"],
                    field_id=item["field_id"],
                    agent_value=item["agent_value"],
                    user_value=item["user_value"],
                    context_snapshot=item.get("context_snapshot", {}),
                    created_at=item.get("created_at", time.time()),
                    last_applied=item.get("last_applied", 0.0),
                    times_applied=item.get("times_applied", 0),
                )
                self._records.append(record)

            logger.info(f"Loaded {len(self._records)} correction records")

        except (json.JSONDecodeError, KeyError, OSError) as e:
            logger.warning(f"Failed to load correction memory: {e}")

    def _save(self) -> None:
        """保存记录到 JSON 文件。"""
        try:
            os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)

            data = {
                "records": [asdict(r) for r in self._records],
                "version": "1.0",
            }

            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

        except OSError as e:
            logger.error(f"Failed to save correction memory: {e}")

    def clear(self) -> None:
        """清空所有记录（仅清内存，不删文件）。"""
        self._records.clear()
        logger.info("CorrectionMemory cleared")
