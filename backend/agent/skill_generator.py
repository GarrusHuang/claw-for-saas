"""
WorkflowAnalyzer — 5.3: 从重复工作流中自动建议生成 Skill。

存储: 复用 user scope 目录的 _workflow_log.json，保留最近 100 条。
fingerprint = 工具名按调用顺序拼接 (去重连续相同工具)。
检测: fingerprint 精确匹配出现 >= threshold 次触发。
"""

from __future__ import annotations

import asyncio
import fcntl
import json
import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MAX_LOG_ENTRIES = 100


class WorkflowAnalyzer:
    """分析用户工作流，检测重复模式并建议 Skill 化。"""

    def __init__(self, memory_store: Any, threshold: int = 3) -> None:
        self.memory_store = memory_store
        self.threshold = threshold

    def _log_path(self, tenant_id: str, user_id: str) -> Path:
        """Get _workflow_log.json path in user scope directory."""
        directory = self.memory_store._resolve_dir(
            "user", tenant_id=tenant_id, user_id=user_id,
        )
        directory.mkdir(parents=True, exist_ok=True)
        return directory / "_workflow_log.json"

    def _load_log(self, tenant_id: str, user_id: str) -> list[dict]:
        path = self._log_path(tenant_id, user_id)
        if not path.exists():
            return []
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

    def _save_log(self, tenant_id: str, user_id: str, log: list[dict]) -> None:
        if len(log) > _MAX_LOG_ENTRIES:
            log = log[-_MAX_LOG_ENTRIES:]
        path = self._log_path(tenant_id, user_id)
        with open(path, "w", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                json.dump(log, f, ensure_ascii=False, indent=2)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def make_fingerprint(tool_names: list[str]) -> str:
        """工具名按调用顺序拼接，去重连续相同工具。"""
        deduped: list[str] = []
        for name in tool_names:
            if not deduped or deduped[-1] != name:
                deduped.append(name)
        return "|".join(deduped)

    def record_workflow(
        self, tenant_id: str, user_id: str, tool_names: list[str],
    ) -> None:
        """记录一次工作流。工具调用 < 3 不记录。"""
        if len(tool_names) < 3:
            return
        fingerprint = self.make_fingerprint(tool_names)
        log = self._load_log(tenant_id, user_id)
        log.append({
            "fingerprint": fingerprint,
            "tools": tool_names,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        self._save_log(tenant_id, user_id, log)

    def detect_repeated(
        self, tenant_id: str, user_id: str,
    ) -> list[dict] | None:
        """检测重复工作流，返回达到阈值的列表或 None。"""
        log = self._load_log(tenant_id, user_id)
        if not log:
            return None

        fp_counts = Counter(entry["fingerprint"] for entry in log)
        repeated: list[dict] = []

        for fp, count in fp_counts.items():
            if count >= self.threshold:
                # 取最近一次的 tools 列表
                for entry in reversed(log):
                    if entry["fingerprint"] == fp:
                        repeated.append({
                            "fingerprint": fp,
                            "count": count,
                            "tools": entry["tools"],
                        })
                        break

        return repeated if repeated else None

    async def generate_skill_draft(
        self,
        fingerprint: str,
        tool_names: list[str],
        llm_client: Any,
    ) -> dict | None:
        """用 LLM 生成 Skill 草稿。返回 {"name", "description", "body"} 或 None。"""
        prompt = (
            "基于以下重复执行的工具调用序列，生成一个 Skill 草稿。\n\n"
            f"工具序列: {' → '.join(tool_names)}\n"
            f"指纹: {fingerprint}\n\n"
            "请生成:\n"
            "1. name: Skill 名称 (英文, snake_case)\n"
            "2. description: 一句话中文描述\n"
            "3. body: Skill 的 Markdown 指引内容 (告诉 Agent 如何执行这个流程)\n\n"
            "输出纯 JSON，无其他文字:\n"
            '{"name": "...", "description": "...", "body": "..."}'
        )

        try:
            resp = await asyncio.wait_for(
                llm_client.chat_completion(
                    messages=[
                        {"role": "system", "content": "你是 Skill 生成助手。只输出 JSON。"},
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=500,
                    temperature=0.5,
                ),
                timeout=15.0,
            )
            if not resp.content:
                return None

            text = resp.content.strip()
            # handle markdown code block wrapper
            if text.startswith("```"):
                text = text.split("```", 2)[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()

            return json.loads(text)
        except Exception as e:
            logger.warning(f"Skill draft generation failed: {e}")
            return None
