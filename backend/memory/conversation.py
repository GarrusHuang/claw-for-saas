"""
ConversationMemory: Layer 2 — 对话记忆。

滑动窗口 + 摘要压缩，支持多轮交互。
用户对 Agent 输出的追加修改（如"把住宿费改成480"）通过此层传递。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ConversationTurn:
    """一轮对话记录。"""

    role: str  # "user" | "assistant" | "system"
    content: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


class ConversationMemory:
    """
    对话记忆管理器。

    使用滑动窗口保留最近 N 轮完整对话，
    超出窗口的历史轮次压缩为摘要文本。

    集成方式：
    - Orchestrator 在调用 Agent 前注入到 params["conversation_history"]
    - BaseAgent._build_system_prompt 将其作为 L4 层注入

    Token 管理：
    - 使用简单字符数估算 token（中文约 1.5 字符/token）
    - 当 get_messages() 的估算 token 数超过阈值时建议 compact
    """

    def __init__(
        self,
        session_id: str,
        sliding_window_size: int = 10,
        max_context_tokens: int = 8000,
    ) -> None:
        self.session_id = session_id
        self.sliding_window_size = sliding_window_size
        self.max_context_tokens = max_context_tokens

        self._turns: list[ConversationTurn] = []
        self._summary: str = ""
        self._compacted_count: int = 0  # 已被压缩的轮次数

        logger.info(
            f"ConversationMemory created: session={session_id}, "
            f"window={sliding_window_size}, max_tokens={max_context_tokens}"
        )

    # ─────────────────────────────────────────────────────────────
    # 对话管理
    # ─────────────────────────────────────────────────────────────

    def add_turn(self, role: str, content: str, metadata: dict[str, Any] | None = None) -> None:
        """添加一轮对话。"""
        turn = ConversationTurn(
            role=role,
            content=content,
            metadata=metadata or {},
        )
        self._turns.append(turn)
        logger.debug(
            f"Turn added: role={role}, length={len(content)}, "
            f"total_turns={len(self._turns)}"
        )

    def get_messages(self) -> list[dict[str, str]]:
        """
        返回当前窗口内的消息列表。

        格式与 OpenAI messages 兼容：[{"role": "user", "content": "..."}]
        只返回窗口内的消息（最近 sliding_window_size 轮）。
        """
        window_start = max(0, len(self._turns) - self.sliding_window_size)
        window_turns = self._turns[window_start:]
        return [{"role": t.role, "content": t.content} for t in window_turns]

    def get_all_messages(self) -> list[dict[str, str]]:
        """返回所有消息（包括窗口外的）。"""
        return [{"role": t.role, "content": t.content} for t in self._turns]

    @property
    def turn_count(self) -> int:
        """当前总轮次数。"""
        return len(self._turns)

    @property
    def window_turns(self) -> list[ConversationTurn]:
        """窗口内的轮次。"""
        window_start = max(0, len(self._turns) - self.sliding_window_size)
        return self._turns[window_start:]

    # ─────────────────────────────────────────────────────────────
    # 摘要管理
    # ─────────────────────────────────────────────────────────────

    def get_summary(self) -> str:
        """
        返回历史摘要。

        如果有被压缩的历史轮次，返回摘要文本；
        否则返回空字符串。
        """
        return self._summary

    def set_summary(self, summary: str) -> None:
        """设置历史摘要（由外部 LLM 生成）。"""
        self._summary = summary
        logger.info(f"Summary updated: {len(summary)} chars")

    def should_compact(self) -> bool:
        """
        判断是否需要压缩。

        任一条件满足即触发：
        1. 轮次数超过窗口大小（窗口外有未压缩消息）
        2. 估算 token 数超过阈值
        """
        # 条件 1：轮次数超过窗口大小
        if len(self._turns) > self.sliding_window_size:
            return True

        # 条件 2：估算 token 数超过阈值
        estimated_tokens = self._estimate_tokens()
        return estimated_tokens > self.max_context_tokens

    def compact(self, summary: str | None = None) -> list[dict[str, str]]:
        """
        压缩窗口外的消息。

        如果提供 summary，使用该摘要替代窗口外的消息。
        如果不提供 summary，自动生成一个简单摘要。

        Args:
            summary: 外部 LLM 生成的摘要（可选）

        Returns:
            被压缩掉的消息列表（用于审计或调试）
        """
        if len(self._turns) <= self.sliding_window_size:
            return []

        # 分割：窗口外 vs 窗口内
        window_start = len(self._turns) - self.sliding_window_size
        compacted_turns = self._turns[:window_start]
        remaining_turns = self._turns[window_start:]

        # 生成摘要
        if summary:
            self._summary = summary
        else:
            # 简单自动摘要（生产环境应使用 LLM）
            self._summary = self._auto_summarize(compacted_turns)

        # 记录压缩了多少轮
        self._compacted_count += len(compacted_turns)

        # 清理
        compacted_messages = [
            {"role": t.role, "content": t.content} for t in compacted_turns
        ]
        self._turns = remaining_turns

        logger.info(
            f"Compacted {len(compacted_turns)} turns, "
            f"total_compacted={self._compacted_count}, "
            f"remaining={len(self._turns)}"
        )

        return compacted_messages

    # ─────────────────────────────────────────────────────────────
    # Prompt 注入
    # ─────────────────────────────────────────────────────────────

    def build_context_prompt(self) -> str:
        """
        构建用于注入 L4 系统提示的对话历史上下文。

        格式：
        - 如果有摘要，先展示摘要
        - 然后展示窗口内的最近消息
        """
        parts: list[str] = []

        if self._summary:
            parts.append(f"【历史对话摘要】\n{self._summary}")

        window_msgs = self.get_messages()
        if window_msgs:
            parts.append("【最近对话】")
            for msg in window_msgs:
                role_label = "用户" if msg["role"] == "user" else "助手"
                parts.append(f"  {role_label}: {msg['content']}")

        return "\n".join(parts) if parts else ""

    # ─────────────────────────────────────────────────────────────
    # 内部方法
    # ─────────────────────────────────────────────────────────────

    def _estimate_tokens(self) -> int:
        """
        估算当前所有消息的 token 数。

        简单估算：中文约 1.5 字符/token，英文约 4 字符/token。
        统一使用 2 字符/token 作为折中。
        """
        total_chars = sum(len(t.content) for t in self._turns)
        if self._summary:
            total_chars += len(self._summary)
        return total_chars // 2

    def _auto_summarize(self, turns: list[ConversationTurn]) -> str:
        """
        简单自动摘要（不使用 LLM）。

        仅用于 Demo 场景或 LLM 不可用时的降级。
        生产环境应使用 LLM 生成高质量摘要。
        """
        if not turns:
            return ""

        summary_parts = []
        summary_parts.append(f"前 {len(turns)} 轮对话摘要:")

        # 只保留用户消息的关键信息
        user_messages = [t for t in turns if t.role == "user"]
        for msg in user_messages[-3:]:  # 最多保留最后 3 条用户消息的摘要
            # 截断过长的消息
            content = msg.content[:100] + "..." if len(msg.content) > 100 else msg.content
            summary_parts.append(f"  - 用户: {content}")

        return "\n".join(summary_parts)

    # ─────────────────────────────────────────────────────────────
    # 序列化
    # ─────────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """序列化为 dict（用于持久化）。"""
        return {
            "session_id": self.session_id,
            "turns": [
                {
                    "role": t.role,
                    "content": t.content,
                    "timestamp": t.timestamp,
                    "metadata": t.metadata,
                }
                for t in self._turns
            ],
            "summary": self._summary,
            "compacted_count": self._compacted_count,
            "config": {
                "sliding_window_size": self.sliding_window_size,
                "max_context_tokens": self.max_context_tokens,
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> ConversationMemory:
        """从 dict 反序列化。"""
        config = data.get("config", {})
        memory = cls(
            session_id=data["session_id"],
            sliding_window_size=config.get("sliding_window_size", 10),
            max_context_tokens=config.get("max_context_tokens", 8000),
        )

        for turn_data in data.get("turns", []):
            turn = ConversationTurn(
                role=turn_data["role"],
                content=turn_data["content"],
                timestamp=turn_data.get("timestamp", time.time()),
                metadata=turn_data.get("metadata", {}),
            )
            memory._turns.append(turn)

        memory._summary = data.get("summary", "")
        memory._compacted_count = data.get("compacted_count", 0)

        return memory

    def clear(self) -> None:
        """清空所有对话记录和摘要。"""
        self._turns.clear()
        self._summary = ""
        self._compacted_count = 0
        logger.info(f"ConversationMemory cleared: session={self.session_id}")
