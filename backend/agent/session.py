"""
Session 管理 — JSONL 会话存储 + 用户隔离。

对标 OpenClaw sessions:
- 存储路径: data/sessions/{user_id}/{session_id}.jsonl
- 每行一条消息 (append-only, crash-safe)
- 支持上下文压缩 (compaction)
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SessionManager:
    """
    用户隔离的会话管理。

    Features:
    - JSONL append-only 存储 (crash-safe)
    - 用户级目录隔离
    - 上下文压缩 (对话过长时自动摘要)
    - 会话元数据追踪
    """

    def __init__(self, base_dir: str = "data/sessions") -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def create_session(self, user_id: str, metadata: dict | None = None) -> str:
        """创建新会话，返回 session_id。"""
        session_id = f"sess-{uuid.uuid4().hex[:12]}"
        user_dir = self.base_dir / user_id
        user_dir.mkdir(parents=True, exist_ok=True)

        # 写入元数据行
        meta_line = {
            "type": "metadata",
            "session_id": session_id,
            "user_id": user_id,
            "created_at": time.time(),
            **(metadata or {}),
        }
        session_file = user_dir / f"{session_id}.jsonl"
        with open(session_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(meta_line, ensure_ascii=False) + "\n")

        logger.info(f"Session created: {session_id} for user {user_id}")
        return session_id

    def load_messages(self, user_id: str, session_id: str) -> list[dict]:
        """加载会话历史消息 (过滤元数据行)。"""
        session_file = self.base_dir / user_id / f"{session_id}.jsonl"
        if not session_file.exists():
            return []

        messages = []
        with open(session_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("type") == "metadata":
                        continue
                    if entry.get("type") == "compaction_marker":
                        continue
                    if entry.get("role") in ("user", "assistant", "system", "tool"):
                        messages.append(entry)
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSONL line in {session_file}")
                    continue
        return messages

    def append_message(self, user_id: str, session_id: str, message: dict) -> None:
        """追加消息 (append-only JSONL)。"""
        session_file = self.base_dir / user_id / f"{session_id}.jsonl"
        if not session_file.exists():
            # 自动创建
            session_file.parent.mkdir(parents=True, exist_ok=True)

        with open(session_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(message, ensure_ascii=False) + "\n")

    async def compact(
        self,
        user_id: str,
        session_id: str,
        llm_client: Any,
        max_recent: int = 6,
    ) -> None:
        """
        上下文压缩。

        当对话历史过长时:
        1. 将消息分为前半 + 后半
        2. 用 LLM 对前半生成摘要
        3. 保留: [摘要消息] + 后半原始消息
        4. 重写会话文件
        """
        messages = self.load_messages(user_id, session_id)
        if len(messages) <= max_recent * 2:
            return  # 不需要压缩

        # 分割点: 保留最近 max_recent 轮
        split_idx = len(messages) - max_recent
        old_messages = messages[:split_idx]
        recent_messages = messages[split_idx:]

        # 生成摘要
        summary_prompt = (
            "请用中文简要总结以下对话的关键信息、决策和结果。"
            "保留所有重要的数据点、用户偏好和业务决策。\n\n"
        )
        for msg in old_messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if content:
                summary_prompt += f"[{role}]: {content[:500]}\n"

        try:
            response = await llm_client.chat_completion(
                messages=[
                    {"role": "system", "content": "你是一个对话摘要助手。"},
                    {"role": "user", "content": summary_prompt},
                ],
                max_tokens=1024,
            )
            summary = response.content or "（对话摘要生成失败）"
        except Exception as e:
            logger.error(f"Compaction failed: {e}")
            summary = f"（前 {len(old_messages)} 轮对话的摘要生成失败）"

        # 重写会话文件 — 保留原始元数据行
        session_file = self.base_dir / user_id / f"{session_id}.jsonl"

        # 读取原始元数据
        original_metadata = None
        try:
            with open(session_file, "r", encoding="utf-8") as f:
                first_line = f.readline().strip()
                if first_line:
                    entry = json.loads(first_line)
                    if entry.get("type") == "metadata":
                        original_metadata = entry
        except Exception:
            pass

        compacted_messages = [
            {"type": "compaction_marker", "compacted_count": len(old_messages), "ts": time.time()},
            {"role": "system", "content": f"[对话历史摘要]\n{summary}"},
            *recent_messages,
        ]

        with open(session_file, "w", encoding="utf-8") as f:
            # 先写回原始元数据行 (供 list_sessions 读取)
            if original_metadata:
                f.write(json.dumps(original_metadata, ensure_ascii=False) + "\n")
            # 写入压缩后的消息
            for msg in compacted_messages:
                f.write(json.dumps(msg, ensure_ascii=False) + "\n")

        logger.info(f"Session {session_id} compacted: {len(old_messages)} messages → summary")

    def list_sessions(self, user_id: str) -> list[dict]:
        """列出用户的所有会话。"""
        user_dir = self.base_dir / user_id
        if not user_dir.exists():
            return []

        sessions = []
        for f in sorted(user_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
            session_id = f.stem
            # 读取元数据行
            metadata = {"session_id": session_id}
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    first_line = fh.readline().strip()
                    if first_line:
                        entry = json.loads(first_line)
                        if entry.get("type") == "metadata":
                            metadata.update(entry)
            except Exception:
                pass
            sessions.append(metadata)
        return sessions

    def delete_session(self, user_id: str, session_id: str) -> bool:
        """删除会话。"""
        session_file = self.base_dir / user_id / f"{session_id}.jsonl"
        if session_file.exists():
            session_file.unlink()
            logger.info(f"Session deleted: {session_id}")
            return True
        return False

    def save_plan_steps(self, user_id: str, session_id: str, steps: list[dict]) -> None:
        """持久化 plan steps 到会话文件 (供 EXECUTE 模式重建 PlanTracker)。"""
        self.append_message(user_id, session_id, {
            "type": "plan_data",
            "steps": steps,
        })

    def load_plan_steps(self, user_id: str, session_id: str) -> list[dict] | None:
        """从会话文件中读取最新的 plan steps。"""
        session_file = self.base_dir / user_id / f"{session_id}.jsonl"
        if not session_file.exists():
            return None

        last_steps = None
        with open(session_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("type") == "plan_data":
                        last_steps = entry.get("steps")
                except json.JSONDecodeError:
                    continue
        return last_steps

    def session_exists(self, user_id: str, session_id: str) -> bool:
        """检查会话是否存在。"""
        return (self.base_dir / user_id / f"{session_id}.jsonl").exists()
