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
import logging
import os
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

    # ─── Prompt 注入 ──────────────────────────────────────────

    def build_memory_prompt(
        self,
        tenant_id: str = "default",
        user_id: str = "anonymous",
    ) -> str:
        """
        构建 <memory> XML 块, 注入 system prompt L5 层。

        读取 global + tenant + user 三级, 按优先级拼接。
        总字符控制在 max_prompt_chars 内。
        """
        sections: list[tuple[str, str]] = []

        global_content = self.read_all("global")
        if global_content:
            sections.append(("global", global_content))

        tenant_content = self.read_all("tenant", tenant_id=tenant_id)
        if tenant_content:
            sections.append(("tenant", tenant_content))

        user_content = self.read_all("user", tenant_id=tenant_id, user_id=user_id)
        if user_content:
            sections.append(("user", user_content))

        if not sections:
            return ""

        # 按优先级裁剪: user > tenant > global
        # 先预留高优先级, 低优先级截断
        budget = self.max_prompt_chars
        final_sections: list[tuple[str, str]] = []

        # 倒序处理 (user 最后加入 sections 列表, 但优先级最高)
        for tag, content in reversed(sections):
            if budget <= 0:
                break
            if len(content) <= budget:
                final_sections.append((tag, content))
                budget -= len(content)
            else:
                # 截断低优先级内容
                truncated = content[:budget] + "\n[...truncated...]"
                final_sections.append((tag, truncated))
                budget = 0

        # 恢复原始顺序 (global → tenant → user)
        final_sections.reverse()

        parts: list[str] = []
        for tag, content in final_sections:
            parts.append(f"<{tag}>\n{content}\n</{tag}>")

        return "\n".join(parts)

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
