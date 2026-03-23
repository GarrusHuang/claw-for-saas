"""
MarkdownMemoryStore: A8 — Markdown 分层笔记记忆系统。

三级目录:
  data/memory/global/                    — 全局层 (跨租户共享)
  data/memory/tenant/{tenant_id}/        — 租户层
  data/memory/user/{tenant_id}/{user_id}/ — 用户层

每层可有多个 .md 文件, Agent 像管理笔记本一样管理自己的记忆。
LLM 自行判断相关性, 无需代码做结构化查询。

并发保护: fcntl.flock() 文件锁。
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 默认 memory 根目录
_DEFAULT_MEMORY_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "memory",
)

# 单个文件最大字节 (超过此值建议 LLM 重写压缩)
DEFAULT_MAX_FILE_BYTES = 50 * 1024  # 50KB

# 注入 prompt 时的最大总字符数
DEFAULT_MAX_PROMPT_CHARS = 8000


class MarkdownMemoryStore:
    """
    Markdown 分层笔记记忆存储。

    三级目录: global / tenant / user
    每级包含若干 .md 文件, Agent 自由读写。
    """

    def __init__(
        self,
        base_dir: str | None = None,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
        max_prompt_chars: int = DEFAULT_MAX_PROMPT_CHARS,
    ) -> None:
        self.base_dir = Path(base_dir or _DEFAULT_MEMORY_DIR)
        self.max_file_bytes = max_file_bytes
        self.max_prompt_chars = max_prompt_chars
        self.base_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"MarkdownMemoryStore initialized: {self.base_dir}")

    # ─── 路径解析 ─────────────────────────────────────────────

    def _resolve_dir(
        self,
        scope: str,
        tenant_id: str = "",
        user_id: str = "",
    ) -> Path:
        """解析 scope → 目录路径。"""
        scope = scope.lower().strip()
        if scope == "global":
            return self.base_dir / "global"
        elif scope == "tenant":
            tid = self._sanitize(tenant_id or "default")
            return self.base_dir / "tenant" / tid
        elif scope == "user":
            tid = self._sanitize(tenant_id or "default")
            uid = self._sanitize(user_id or "anonymous")
            return self.base_dir / "user" / tid / uid
        else:
            raise ValueError(f"Invalid scope: {scope!r} (must be global/tenant/user)")

    def _resolve_file(
        self,
        scope: str,
        filename: str,
        tenant_id: str = "",
        user_id: str = "",
    ) -> Path:
        """解析 scope + filename → 文件路径。"""
        directory = self._resolve_dir(scope, tenant_id, user_id)
        safe_name = self._sanitize(filename)
        if not safe_name.endswith(".md"):
            safe_name += ".md"
        return directory / safe_name

    # ─── 读写操作 ─────────────────────────────────────────────

    def read_file(
        self,
        scope: str,
        filename: str,
        tenant_id: str = "",
        user_id: str = "",
    ) -> str:
        """读取指定 .md 文件内容, 不存在返回空字符串。"""
        path = self._resolve_file(scope, filename, tenant_id, user_id)
        if not path.exists():
            return ""
        try:
            return path.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning(f"Failed to read {path}: {e}")
            return ""

    def write_file(
        self,
        scope: str,
        filename: str,
        content: str,
        mode: str = "append",
        tenant_id: str = "",
        user_id: str = "",
    ) -> bool:
        """
        写入 .md 文件。

        Args:
            mode: "append" 追加 | "rewrite" 覆盖
        Returns:
            是否成功
        """
        path = self._resolve_file(scope, filename, tenant_id, user_id)
        path.parent.mkdir(parents=True, exist_ok=True)

        try:
            if mode == "rewrite":
                self._write_with_lock(path, content)
            else:
                # append — read-modify-write 全部在文件锁内完成，
                # 防止两个 worker 同时读到旧内容导致 lost update
                self._append_with_lock(path, content)
            return True
        except OSError as e:
            logger.error(f"Failed to write {path}: {e}")
            return False

    def list_files(
        self,
        scope: str,
        tenant_id: str = "",
        user_id: str = "",
    ) -> list[str]:
        """列出某层级下所有 .md 文件名。"""
        directory = self._resolve_dir(scope, tenant_id, user_id)
        if not directory.exists():
            return []
        return sorted(f.name for f in directory.glob("*.md"))

    def read_all(
        self,
        scope: str,
        tenant_id: str = "",
        user_id: str = "",
    ) -> str:
        """读取某层级下所有 .md 文件, 拼接返回。"""
        files = self.list_files(scope, tenant_id, user_id)
        if not files:
            return ""
        parts: list[str] = []
        for fname in files:
            content = self.read_file(scope, fname, tenant_id, user_id)
            if content.strip():
                parts.append(content.strip())
        return "\n\n".join(parts)

    def delete_file(
        self,
        scope: str,
        filename: str,
        tenant_id: str = "",
        user_id: str = "",
    ) -> bool:
        """删除指定 .md 文件。"""
        path = self._resolve_file(scope, filename, tenant_id, user_id)
        if not path.exists():
            return False
        try:
            path.unlink()
            return True
        except OSError as e:
            logger.error(f"Failed to delete {path}: {e}")
            return False

    def append_memory(
        self,
        scope: str,
        filename: str,
        content: str,
        tenant_id: str = "",
        user_id: str = "",
    ) -> bool:
        """追加内容到记忆文件 (便捷方法，等同于 write_file mode='append')。"""
        return self.write_file(scope, filename, content, mode="append",
                               tenant_id=tenant_id, user_id=user_id)

    # ─── _meta.json 元数据 (5.3: 记忆引用追踪) ──────────────

    def _meta_path(self, scope: str, tenant_id: str = "", user_id: str = "") -> Path:
        """获取 _meta.json 的路径。"""
        return self._resolve_dir(scope, tenant_id, user_id) / "_meta.json"

    def _load_meta(self, scope: str, tenant_id: str = "", user_id: str = "") -> dict:
        """加载 _meta.json，不存在返回空结构。"""
        path = self._meta_path(scope, tenant_id, user_id)
        if not path.exists():
            return {"entries": {}}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to load _meta.json at {path}: {e}")
            return {"entries": {}}

    def _save_meta(self, scope: str, meta: dict, tenant_id: str = "", user_id: str = "") -> None:
        """带 fcntl 锁写入 _meta.json。"""
        path = self._meta_path(scope, tenant_id, user_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _parse_entries(content: str, filename: str) -> list[tuple[str, str]]:
        """按 ## 分段返回 [(entry_key, text)]。无 ## 段落的文件用 __full__。"""
        sections: list[tuple[str, str]] = []
        current_header: str | None = None
        current_lines: list[str] = []

        for line in content.split("\n"):
            if line.startswith("## "):
                if current_header is not None:
                    text = "\n".join(current_lines).strip()
                    if text:
                        sections.append((f"{filename}::{current_header}", text))
                current_header = line[3:].strip()
                current_lines = [line]
            else:
                if current_header is not None:
                    current_lines.append(line)

        # flush last section
        if current_header is not None:
            text = "\n".join(current_lines).strip()
            if text:
                sections.append((f"{filename}::{current_header}", text))

        # 无 ## 段落 → 整个文件作为一个条目
        if not sections and content.strip():
            sections.append((f"{filename}::__full__", content.strip()))

        return sections

    def increment_usage(
        self, scope: str, entry_key: str, tenant_id: str = "", user_id: str = "",
    ) -> None:
        """递增 usage_count + 更新 last_used。"""
        meta = self._load_meta(scope, tenant_id, user_id)
        entries = meta.setdefault("entries", {})
        now = datetime.now(timezone.utc).isoformat()
        if entry_key in entries:
            entries[entry_key]["usage_count"] = entries[entry_key].get("usage_count", 0) + 1
            entries[entry_key]["last_used"] = now
        else:
            entries[entry_key] = {"usage_count": 1, "last_used": now, "created_at": now}
        self._save_meta(scope, meta, tenant_id, user_id)

    def get_usage_stats(
        self, scope: str, tenant_id: str = "", user_id: str = "",
    ) -> list[dict]:
        """按 usage_count 降序返回所有条目统计。"""
        meta = self._load_meta(scope, tenant_id, user_id)
        result = [
            {
                "entry_key": key,
                "usage_count": info.get("usage_count", 0),
                "last_used": info.get("last_used", ""),
                "created_at": info.get("created_at", ""),
            }
            for key, info in meta.get("entries", {}).items()
        ]
        result.sort(key=lambda x: x["usage_count"], reverse=True)
        return result

    # ─── Prompt 注入 ──────────────────────────────────────────

    def build_memory_prompt(
        self,
        tenant_id: str = "default",
        user_id: str = "anonymous",
    ) -> tuple[str, dict[str, tuple[str, str]]]:
        """
        构建 <memory> XML 块, 注入 system prompt L5 层。

        读取 global + tenant + user 三级, 每个段落分配短 ID (m1, m2, ...)。
        同 scope 内按 usage_count 降序排列。总字符控制在 max_prompt_chars 内。

        Returns:
            (prompt_text, id_map) — id_map: {"m1": ("scope", "entry_key"), ...}
        """
        scope_configs = [
            ("global", {}),
            ("tenant", {"tenant_id": tenant_id}),
            ("user", {"tenant_id": tenant_id, "user_id": user_id}),
        ]

        # ── 收集每个 scope 的段落, 按 usage_count 排序 ──
        scope_data: list[tuple[str, list[tuple[str, str]]]] = []

        for scope_name, kwargs in scope_configs:
            files = self.list_files(scope_name, **kwargs)
            if not files:
                continue
            meta_entries = self._load_meta(scope_name, **kwargs).get("entries", {})

            all_entries: list[tuple[str, str, int]] = []  # (entry_key, text, usage_count)
            for fname in files:
                content = self.read_file(scope_name, fname, **kwargs)
                if not content.strip():
                    continue
                for entry_key, text in self._parse_entries(content, fname):
                    uc = meta_entries.get(entry_key, {}).get("usage_count", 0)
                    all_entries.append((entry_key, text, uc))

            all_entries.sort(key=lambda x: x[2], reverse=True)
            if all_entries:
                scope_data.append((scope_name, [(k, t) for k, t, _ in all_entries]))

        if not scope_data:
            return ("", {})

        # ── 按优先级分配预算: user > tenant > global ──
        budget = self.max_prompt_chars
        id_counter = 1
        id_map: dict[str, tuple[str, str]] = {}
        allocated: list[tuple[str, list[str]]] = []

        for scope_name, entries in reversed(scope_data):
            if budget <= 0:
                break
            parts: list[str] = []
            for entry_key, text in entries:
                if budget <= 0:
                    break
                mid = f"m{id_counter}"
                prefixed = f"[{mid}] {text}"
                cost = len(prefixed) + 2  # \n\n separator
                if cost <= budget:
                    parts.append(prefixed)
                    id_map[mid] = (scope_name, entry_key)
                    id_counter += 1
                    budget -= cost
                else:
                    overhead = len(f"[{mid}] ") + len("\n[...truncated...]")
                    remaining = budget - overhead
                    if remaining > 20:
                        parts.append(f"[{mid}] {text[:remaining]}\n[...truncated...]")
                        id_map[mid] = (scope_name, entry_key)
                        id_counter += 1
                    budget = 0
                    break
            if parts:
                allocated.append((scope_name, parts))

        allocated.reverse()  # 恢复 global → tenant → user 顺序

        text_parts: list[str] = []
        for scope_name, parts in allocated:
            content = "\n\n".join(parts)
            text_parts.append(f"<{scope_name}>\n{content}\n</{scope_name}>")

        return ("\n".join(text_parts), id_map)

    # ─── 记忆合并 (Phase 4B) ──────────────────────────────────

    def needs_merge(
        self,
        tenant_id: str = "default",
        user_id: str = "anonymous",
    ) -> bool:
        """检查 auto-learning.md 是否超过合并阈值 (50KB)。"""
        path = self._resolve_file("user", "auto-learning.md", tenant_id, user_id)
        if not path.exists():
            return False
        return path.stat().st_size > self.max_file_bytes

    async def merge_auto_learning(
        self,
        tenant_id: str,
        user_id: str,
        llm_client: Any,
    ) -> bool:
        """
        合并 auto-learning.md 为 memory_summary.md。

        使用 LLM 去重、分类、压缩。合并后清空 auto-learning.md。
        """
        import asyncio

        auto_content = self.read_file("user", "auto-learning.md", tenant_id, user_id)
        if not auto_content.strip():
            return False

        existing_summary = self.read_file("user", "memory_summary.md", tenant_id, user_id)

        merge_prompt = (
            "请将以下 <auto_learning> 中的记忆条目与 <existing_summary> 合并，"
            "生成一份结构化的记忆摘要。\n\n"
            "规则:\n"
            "1. 去重: 相同或相似的条目合并为一条\n"
            "2. 分类: 按 [偏好] [纠正] [决策] [角色] 分组\n"
            "3. 压缩: 每条简洁但保留关键信息\n"
            "4. 删除过时信息 (如果新条目明确否定了旧条目)\n"
            "5. 总长度控制在 3000 字以内\n\n"
            f"<existing_summary>\n{existing_summary[:3000]}\n</existing_summary>\n\n"
            f"<auto_learning>\n{auto_content[:5000]}\n</auto_learning>"
        )

        try:
            resp = await asyncio.wait_for(
                llm_client.chat_completion(
                    messages=[
                        {"role": "system", "content": "你是记忆合并助手。输出结构化的记忆摘要。"},
                        {"role": "user", "content": merge_prompt},
                    ],
                    max_tokens=1000,
                    temperature=0.3,
                ),
                timeout=30.0,
            )
            if resp.content and len(resp.content.strip()) > 20:
                # 写入 memory_summary.md
                self.write_file(
                    "user", "memory_summary.md", resp.content.strip(),
                    mode="rewrite", tenant_id=tenant_id, user_id=user_id,
                )
                # 清空 auto-learning.md
                self.write_file(
                    "user", "auto-learning.md", "",
                    mode="rewrite", tenant_id=tenant_id, user_id=user_id,
                )
                logger.info(f"Merged auto-learning into memory_summary for {tenant_id}/{user_id}")
                return True
        except Exception as e:
            logger.warning(f"Memory merge failed: {e}")

        return False

    async def scan_and_merge_all(
        self,
        llm_client: Any,
        max_per_run: int = 50,
    ) -> int:
        """
        扫描 data/memory/user/ 全部目录，对超 50KB 的 auto-learning.md 执行合并。

        Returns:
            合并成功的用户数。
        """
        user_dir = self.base_dir / "user"
        if not user_dir.exists():
            return 0

        merged_count = 0
        processed = 0

        # 遍历 user_dir/{tenant_id}/{user_id}/
        for tenant_dir in sorted(user_dir.iterdir()):
            if not tenant_dir.is_dir():
                continue
            tenant_id = tenant_dir.name
            for uid_dir in sorted(tenant_dir.iterdir()):
                if not uid_dir.is_dir():
                    continue
                if processed >= max_per_run:
                    break
                user_id = uid_dir.name
                if self.needs_merge(tenant_id=tenant_id, user_id=user_id):
                    processed += 1
                    try:
                        ok = await self.merge_auto_learning(tenant_id, user_id, llm_client)
                        if ok:
                            merged_count += 1
                    except Exception as e:
                        logger.warning(f"Merge failed for {tenant_id}/{user_id}: {e}")
            if processed >= max_per_run:
                break

        return merged_count

    # ─── 过期清理 (5.3) ──────────────────────────────────────

    def cleanup_expired_entries(
        self,
        scope: str,
        tenant_id: str = "",
        user_id: str = "",
        retention_days: int = 30,
    ) -> int:
        """
        清理 _meta.json 中已过期的记忆条目。

        条件: last_used (或 created_at) 超过 retention_days 且 usage_count == 0。
        保护规则: usage_count > 0 的永不清理。

        Returns:
            清理的条目数。
        """
        if retention_days <= 0:
            return 0

        meta = self._load_meta(scope, tenant_id, user_id)
        entries = meta.get("entries", {})
        if not entries:
            return 0

        now = datetime.now(timezone.utc)
        to_remove: list[str] = []

        for key, info in entries.items():
            if info.get("usage_count", 0) > 0:
                continue
            ts_str = info.get("last_used") or info.get("created_at", "")
            if not ts_str:
                continue
            try:
                ts = datetime.fromisoformat(ts_str)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                age_days = (now - ts).days
                if age_days >= retention_days:
                    to_remove.append(key)
            except (ValueError, TypeError):
                continue

        if not to_remove:
            return 0

        # ── 从 .md 文件中删除对应段落 ──
        kwargs = {"tenant_id": tenant_id, "user_id": user_id} if scope != "global" else {}
        if scope == "tenant":
            kwargs = {"tenant_id": tenant_id}
        elif scope == "user":
            kwargs = {"tenant_id": tenant_id, "user_id": user_id}
        else:
            kwargs = {}

        files_to_rewrite: dict[str, list[str]] = {}  # filename → [headers_to_remove]
        for key in to_remove:
            parts = key.split("::", 1)
            if len(parts) != 2:
                continue
            filename, header = parts
            files_to_rewrite.setdefault(filename, []).append(header)

        for filename, headers in files_to_rewrite.items():
            content = self.read_file(scope, filename, **kwargs)
            if not content:
                continue
            parsed = self._parse_entries(content, filename)
            remaining = [
                text for ek, text in parsed
                if ek.split("::", 1)[1] not in headers
            ]
            new_content = "\n\n".join(remaining)
            if new_content.strip():
                self.write_file(scope, filename, new_content, mode="rewrite", **kwargs)
            else:
                self.delete_file(scope, filename, **kwargs)

        # ── 从 _meta.json 删除条目 ──
        for key in to_remove:
            entries.pop(key, None)
        self._save_meta(scope, meta, tenant_id, user_id)

        logger.info(f"Cleaned {len(to_remove)} expired memory entries in {scope}")
        return len(to_remove)

    def scan_and_cleanup_expired(
        self,
        retention_days: int = 30,
        max_per_run: int = 100,
    ) -> int:
        """
        扫描 data/memory/user/ 全部目录，清理过期记忆条目。

        Returns:
            清理的总条目数。
        """
        if retention_days <= 0:
            return 0

        user_dir = self.base_dir / "user"
        if not user_dir.exists():
            return 0

        total_cleaned = 0
        processed = 0

        for tenant_dir in sorted(user_dir.iterdir()):
            if not tenant_dir.is_dir():
                continue
            tenant_id = tenant_dir.name
            for uid_dir in sorted(tenant_dir.iterdir()):
                if not uid_dir.is_dir():
                    continue
                if processed >= max_per_run:
                    break
                user_id = uid_dir.name
                processed += 1
                try:
                    cleaned = self.cleanup_expired_entries(
                        "user", tenant_id=tenant_id, user_id=user_id,
                        retention_days=retention_days,
                    )
                    total_cleaned += cleaned
                except Exception as e:
                    logger.warning(f"Cleanup failed for {tenant_id}/{user_id}: {e}")
            if processed >= max_per_run:
                break

        return total_cleaned

    # ─── 统计 ────────────────────────────────────────────────

    def get_stats(
        self,
        tenant_id: str = "",
        user_id: str = "",
    ) -> dict[str, Any]:
        """返回存储统计信息。"""
        stats: dict[str, Any] = {
            "global_files": len(self.list_files("global")),
            "tenant_files": 0,
            "user_files": 0,
            "total_size_bytes": 0,
        }

        # Global size
        global_dir = self._resolve_dir("global")
        if global_dir.exists():
            for f in global_dir.glob("*.md"):
                stats["total_size_bytes"] += f.stat().st_size

        # Tenant
        if tenant_id:
            tenant_files = self.list_files("tenant", tenant_id=tenant_id)
            stats["tenant_files"] = len(tenant_files)
            tenant_dir = self._resolve_dir("tenant", tenant_id=tenant_id)
            if tenant_dir.exists():
                for f in tenant_dir.glob("*.md"):
                    stats["total_size_bytes"] += f.stat().st_size

        # User
        if tenant_id and user_id:
            user_files = self.list_files("user", tenant_id=tenant_id, user_id=user_id)
            stats["user_files"] = len(user_files)
            user_dir = self._resolve_dir("user", tenant_id=tenant_id, user_id=user_id)
            if user_dir.exists():
                for f in user_dir.glob("*.md"):
                    stats["total_size_bytes"] += f.stat().st_size

        return stats

    def file_needs_compaction(
        self,
        scope: str,
        filename: str,
        tenant_id: str = "",
        user_id: str = "",
    ) -> bool:
        """检查文件是否超过大小阈值, 需要 LLM 重写压缩。"""
        path = self._resolve_file(scope, filename, tenant_id, user_id)
        if not path.exists():
            return False
        return path.stat().st_size > self.max_file_bytes

    # ─── 内部方法 ─────────────────────────────────────────────

    @staticmethod
    def _sanitize(name: str) -> str:
        """防止路径穿越。"""
        return name.replace("/", "_").replace("\\", "_").replace("..", "").strip()

    @staticmethod
    def _write_with_lock(path: Path, content: str) -> None:
        """带文件锁的写入 (防止并发 lost update)。"""
        with open(path, "w", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.write(content)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _append_with_lock(path: Path, content: str) -> None:
        """
        带文件锁的追加写入 — read-modify-write 在同一把锁内完成。

        使用 "r+" 模式 (或新文件用 "w") 打开，先 flock，再读已有内容，
        最后 truncate + 写回。保证多 worker 并发时不会 lost update。
        """
        if not path.exists():
            # 文件不存在 — 直接创建并写入
            with open(path, "w", encoding="utf-8") as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    f.write(content)
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            return

        with open(path, "r+", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                existing = f.read()
                separator = "\n\n" if existing and not existing.endswith("\n\n") else ""
                f.seek(0)
                f.write(existing + separator + content)
                f.truncate()
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
