"""
Session 管理 — JSONL 会话存储 + 租户/用户隔离。

存储路径: data/sessions/{tenant_id}/{user_id}/{session_id}.jsonl
- 每行一条消息 (append-only, crash-safe)
- 支持上下文压缩 (compaction)
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SessionManager:
    """
    租户+用户隔离的会话管理。

    Features:
    - JSONL append-only 存储 (crash-safe)
    - tenant_id + user_id 目录隔离
    - 上下文压缩 (对话过长时自动摘要)
    - 会话元数据追踪
    """

    def __init__(self, base_dir: str = "data/sessions") -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        # #46: 搜索索引缓存 (key → (dir_mtime, index))
        self._search_index_cache: dict[str, tuple[float, list[dict]]] = {}

    def _session_dir(self, tenant_id: str, user_id: str) -> Path:
        """获取 tenant/user 级会话目录。"""
        return self.base_dir / tenant_id / user_id

    def create_session(
        self, tenant_id: str, user_id: str, metadata: dict | None = None
    ) -> str:
        """创建新会话，返回 session_id。"""
        session_id = f"sess-{uuid.uuid4().hex[:12]}"
        session_dir = self._session_dir(tenant_id, user_id)
        session_dir.mkdir(parents=True, exist_ok=True)

        meta_line = {
            "type": "metadata",
            "session_id": session_id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "created_at": time.time(),
            **(metadata or {}),
        }
        session_file = session_dir / f"{session_id}.jsonl"
        with open(session_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(meta_line, ensure_ascii=False) + "\n")

        logger.info(f"Session created: {session_id} for tenant={tenant_id} user={user_id}")
        return session_id

    def load_messages(
        self, tenant_id: str, user_id: str, session_id: str,
        limit: int = 0, offset: int = 0,
    ) -> list[dict]:
        """
        加载会话历史消息 (过滤元数据行)。

        Args:
            limit: 最多返回消息数 (0=全部)
            offset: 跳过前 N 条消息 (从最旧开始)
        """
        session_file = self._session_dir(tenant_id, user_id) / f"{session_id}.jsonl"
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

        # 分页
        if offset > 0:
            messages = messages[offset:]
        if limit > 0:
            messages = messages[:limit]

        return messages

    def cleanup_expired_sessions(self, retention_days: int = 30) -> int:
        """
        清理过期会话 JSONL 文件。

        根据首行 metadata 中的 created_at 时间戳判断是否过期。
        同时删除对应的 .lock 文件。

        Args:
            retention_days: 保留天数 (0=不清理)

        Returns:
            删除的会话文件数量
        """
        if retention_days <= 0:
            return 0

        cutoff = time.time() - retention_days * 86400
        deleted = 0

        for session_file in self.base_dir.rglob("*.jsonl"):
            try:
                with open(session_file, "r", encoding="utf-8") as f:
                    first_line = f.readline().strip()
                if not first_line:
                    continue
                meta = json.loads(first_line)
                created_at = meta.get("created_at", 0)
                if created_at > 0 and created_at < cutoff:
                    session_file.unlink()
                    lock_file = session_file.with_suffix(".lock")
                    if lock_file.exists():
                        lock_file.unlink()
                    deleted += 1
            except Exception:
                continue

        if deleted:
            logger.info(f"Cleaned {deleted} expired session files (retention={retention_days}d)")
        return deleted

    def cleanup_orphan_locks(self, max_age_s: float = 3600) -> int:
        """
        清理孤儿 .lock 文件。

        超过 max_age_s 秒未修改的 .lock 文件会被删除。
        通常在启动时调用一次。

        Returns:
            删除的 lock 文件数量
        """
        now = time.time()
        cleaned = 0
        for lock_file in self.base_dir.rglob("*.lock"):
            try:
                if now - lock_file.stat().st_mtime > max_age_s:
                    lock_file.unlink()
                    cleaned += 1
            except OSError:
                pass
        if cleaned:
            logger.info(f"Cleaned {cleaned} orphan session lock files")
        return cleaned

    def rollback_turns(
        self, tenant_id: str, user_id: str, session_id: str, n: int = 1,
    ) -> int:
        """
        #15 Thread Rollback: 撤销最近 N 轮对话 (每轮 = 1 user + 1 assistant 消息)。

        从 JSONL 文件末尾移除消息。返回实际移除的消息数。
        """
        if n <= 0:
            return 0
        messages = self.load_messages(tenant_id, user_id, session_id)
        if not messages:
            return 0

        # 从末尾计数: 找到最近 n 轮的起始位置
        remove_count = 0
        turns_found = 0
        for msg in reversed(messages):
            remove_count += 1
            if msg.get("role") == "user":
                turns_found += 1
                if turns_found >= n:
                    break

        if remove_count == 0:
            return 0

        keep = messages[:-remove_count]
        # 重写 JSONL
        session_file = self._session_dir(tenant_id, user_id) / f"{session_id}.jsonl"
        # 保留 metadata 行
        raw_lines: list[str] = []
        if session_file.exists():
            with open(session_file, "r", encoding="utf-8") as f:
                for line in f:
                    line_s = line.strip()
                    if not line_s:
                        continue
                    try:
                        entry = json.loads(line_s)
                        if entry.get("type") in ("metadata", "compaction_marker"):
                            raw_lines.append(line_s)
                    except json.JSONDecodeError:
                        pass

        with open(session_file, "w", encoding="utf-8") as f:
            for line in raw_lines:
                f.write(line + "\n")
            for msg in keep:
                f.write(json.dumps(msg, ensure_ascii=False) + "\n")

        logger.info(f"Rolled back {remove_count} messages ({n} turns) from session {session_id}")
        return remove_count

    def append_message(
        self, tenant_id: str, user_id: str, session_id: str, message: dict
    ) -> None:
        """追加消息 (append-only JSONL)。"""
        session_dir = self._session_dir(tenant_id, user_id)
        session_file = session_dir / f"{session_id}.jsonl"
        if not session_file.exists():
            session_dir.mkdir(parents=True, exist_ok=True)

        with open(session_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(message, ensure_ascii=False) + "\n")

    async def compact(
        self,
        tenant_id: str,
        user_id: str,
        session_id: str,
        llm_client: Any,
        max_recent: int = 6,
    ) -> None:
        """上下文压缩。"""
        messages = self.load_messages(tenant_id, user_id, session_id)
        if len(messages) <= max_recent * 2:
            return

        split_idx = len(messages) - max_recent
        old_messages = messages[:split_idx]
        recent_messages = messages[split_idx:]

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

        session_file = self._session_dir(tenant_id, user_id) / f"{session_id}.jsonl"

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

        fd, tmp_path = tempfile.mkstemp(
            dir=str(session_file.parent), suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                if original_metadata:
                    f.write(json.dumps(original_metadata, ensure_ascii=False) + "\n")
                for msg in compacted_messages:
                    f.write(json.dumps(msg, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, str(session_file))
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        logger.info(f"Session {session_id} compacted: {len(old_messages)} messages → summary")

    def list_sessions(self, tenant_id: str, user_id: str) -> list[dict]:
        """列出用户的所有会话。"""
        session_dir = self._session_dir(tenant_id, user_id)
        if not session_dir.exists():
            return []

        sessions = []
        for f in sorted(session_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
            session_id = f.stem
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

    def _build_search_index(self, tenant_id: str, user_id: str) -> list[dict]:
        """
        #46: 构建会话搜索索引 (metadata + 首条用户消息)。

        带缓存: 目录 mtime 不变时复用上次结果。

        Returns:
            [{session_id, title, business_type, first_user_msg, mtime}, ...]
        """
        session_dir = self._session_dir(tenant_id, user_id)
        cache_key = f"{tenant_id}:{user_id}"
        try:
            dir_mtime = session_dir.stat().st_mtime if session_dir.exists() else 0
        except OSError:
            dir_mtime = 0
        cached = self._search_index_cache.get(cache_key)
        if cached and cached[0] >= dir_mtime:
            return cached[1]
        if not session_dir.exists():
            return []

        index = []
        for f in sorted(session_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
            entry = {"session_id": f.stem, "mtime": f.stat().st_mtime}
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if data.get("type") == "metadata":
                            entry["title"] = str(data.get("title", ""))
                            entry["business_type"] = str(data.get("business_type", ""))
                        elif data.get("role") == "user" and "first_user_msg" not in entry:
                            entry["first_user_msg"] = str(data.get("content", ""))[:200]
                        if "title" in entry and "first_user_msg" in entry:
                            break
            except OSError:
                continue
            index.append(entry)
        self._search_index_cache[cache_key] = (dir_mtime, index)
        return index

    def search_sessions(
        self, tenant_id: str, user_id: str, query: str, limit: int = 20
    ) -> list[dict]:
        """搜索会话 — 先搜索索引 (标题+首消息)，未命中再 fallback 全文扫描。"""
        if not query or not query.strip():
            return []

        query_lower = query.strip().lower()
        session_dir = self._session_dir(tenant_id, user_id)
        if not session_dir.exists():
            return []

        # #46: 快速路径 — 搜索索引 (标题 + 首条消息)
        index = self._build_search_index(tenant_id, user_id)
        fast_results = []
        unmatched_files = []
        for entry in index:
            title = entry.get("title", "").lower()
            bt = entry.get("business_type", "").lower()
            first_msg = entry.get("first_user_msg", "").lower()
            if query_lower in title or query_lower in bt or query_lower in first_msg:
                snippet = ""
                if query_lower in first_msg:
                    raw_msg = entry.get("first_user_msg", "")
                    pos = first_msg.find(query_lower)
                    start = max(0, pos - 30)
                    end = min(len(raw_msg), pos + len(query_lower) + 50)
                    snippet = raw_msg[start:end].replace("\n", " ")
                    if start > 0:
                        snippet = "..." + snippet
                    if end < len(raw_msg):
                        snippet = snippet + "..."
                fast_results.append({
                    "session_id": entry["session_id"],
                    "title": entry.get("title", ""),
                    "business_type": entry.get("business_type", ""),
                    "match_snippet": snippet,
                    "title_match": query_lower in title or query_lower in bt,
                })
                if len(fast_results) >= limit:
                    return fast_results
            else:
                unmatched_files.append(entry["session_id"])

        # 快速路径已满足
        if len(fast_results) >= limit:
            return fast_results

        # Fallback: 全文扫描未命中的 JSONL (保留旧逻辑)
        remaining = limit - len(fast_results)
        results = list(fast_results)
        for session_id in unmatched_files:
            if remaining <= 0:
                break
            f = session_dir / f"{session_id}.jsonl"
            if not f.exists():
                continue
            session_id = f.stem
            metadata: dict[str, object] = {"session_id": session_id}
            matched_snippet = ""
            title_match = False

            try:
                with open(f, "r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        # 元数据行 — 检查标题
                        if entry.get("type") == "metadata":
                            metadata.update(entry)
                            title = str(entry.get("title", ""))
                            bt = str(entry.get("business_type", ""))
                            if query_lower in title.lower() or query_lower in bt.lower():
                                title_match = True
                            continue

                        if entry.get("type") == "compaction_marker":
                            continue

                        # 消息行 — 搜索内容
                        if not matched_snippet and entry.get("role") in (
                            "user",
                            "assistant",
                        ):
                            content = str(entry.get("content", ""))
                            pos = content.lower().find(query_lower)
                            if pos >= 0:
                                start = max(0, pos - 30)
                                end = min(len(content), pos + len(query_lower) + 50)
                                snippet = content[start:end].replace("\n", " ")
                                if start > 0:
                                    snippet = "..." + snippet
                                if end < len(content):
                                    snippet = snippet + "..."
                                matched_snippet = snippet

            except Exception:
                logger.warning(f"Error searching session {session_id}")
                continue

            if title_match or matched_snippet:
                results.append({
                    **metadata,
                    "match_snippet": matched_snippet,
                    "title_match": title_match,
                })
                if len(results) >= limit:
                    break

        return results

    def delete_session(self, tenant_id: str, user_id: str, session_id: str) -> bool:
        """删除会话。"""
        session_file = self._session_dir(tenant_id, user_id) / f"{session_id}.jsonl"
        if session_file.exists():
            session_file.unlink()
            logger.info(f"Session deleted: {session_id}")
            return True
        return False

    def save_plan_steps(
        self, tenant_id: str, user_id: str, session_id: str, steps: list[dict]
    ) -> None:
        """持久化 plan steps 到会话文件。"""
        self.append_message(tenant_id, user_id, session_id, {
            "type": "plan_data",
            "steps": steps,
        })

    def load_plan_steps(
        self, tenant_id: str, user_id: str, session_id: str
    ) -> list[dict] | None:
        """从会话文件中读取最新的 plan steps。"""
        session_file = self._session_dir(tenant_id, user_id) / f"{session_id}.jsonl"
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

    def save_timeline(
        self, tenant_id: str, user_id: str, session_id: str,
        entries: list[dict], turn_index: int,
    ) -> None:
        """持久化时间线条目 (thinking + tool_executed) 到会话文件。"""
        self.append_message(tenant_id, user_id, session_id, {
            "type": "timeline_data",
            "turn_index": turn_index,
            "entries": entries,
        })

    def load_timelines(
        self, tenant_id: str, user_id: str, session_id: str
    ) -> list[dict]:
        """从会话文件中读取所有时间线数据。"""
        session_file = self._session_dir(tenant_id, user_id) / f"{session_id}.jsonl"
        if not session_file.exists():
            return []

        timelines: list[dict] = []
        with open(session_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("type") == "timeline_data":
                        timelines.append(entry)
                except json.JSONDecodeError:
                    continue
        return timelines

    def save_loaded_skills(
        self, tenant_id: str, user_id: str, session_id: str, skills: list[str]
    ) -> None:
        """持久化加载的 Skill 列表到会话文件。"""
        self.append_message(tenant_id, user_id, session_id, {
            "type": "loaded_skills",
            "skills": skills,
        })

    def load_loaded_skills(
        self, tenant_id: str, user_id: str, session_id: str
    ) -> list[str] | None:
        """从会话文件中读取最新的 loaded_skills。"""
        session_file = self._session_dir(tenant_id, user_id) / f"{session_id}.jsonl"
        if not session_file.exists():
            return None

        last_skills = None
        with open(session_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("type") == "loaded_skills":
                        last_skills = entry.get("skills")
                except json.JSONDecodeError:
                    continue
        return last_skills

    def session_exists(self, tenant_id: str, user_id: str, session_id: str) -> bool:
        """检查会话是否存在。"""
        return (self._session_dir(tenant_id, user_id) / f"{session_id}.jsonl").exists()
