"""
MemoryStorage: 持久化抽象层。

Demo 模式使用 JSON 文件存储。
生产环境可替换为 SQLite 或其他数据库。

提供统一的 save / load / delete 接口，
隔离 Memory 组件与具体存储实现。
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# 默认数据目录
_DEFAULT_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
)


class MemoryStorage:
    """
    Memory 持久化存储。

    Demo 模式：基于 JSON 文件。
    每个 Memory 组件使用独立的 JSON 文件。

    Usage:
        storage = MemoryStorage(data_dir="data/")
        storage.save("conversation", session_id, data_dict)
        data = storage.load("conversation", session_id)
    """

    def __init__(self, data_dir: str | None = None) -> None:
        self.data_dir = data_dir or _DEFAULT_DATA_DIR
        os.makedirs(self.data_dir, exist_ok=True)
        logger.info(f"MemoryStorage initialized: {self.data_dir}")

    def save(self, namespace: str, key: str, data: dict[str, Any]) -> bool:
        """
        保存数据。

        Args:
            namespace: 命名空间（如 "conversation", "correction", "learning"）
            key: 数据键（如 session_id, user_id）
            data: 要保存的数据

        Returns:
            是否保存成功
        """
        file_path = self._get_path(namespace, key)

        try:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)

            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            logger.debug(f"Saved: {namespace}/{key}")
            return True

        except OSError as e:
            logger.error(f"Failed to save {namespace}/{key}: {e}")
            return False

    def load(self, namespace: str, key: str) -> dict[str, Any] | None:
        """
        加载数据。

        Args:
            namespace: 命名空间
            key: 数据键

        Returns:
            加载的数据，不存在时返回 None
        """
        file_path = self._get_path(namespace, key)

        if not os.path.exists(file_path):
            return None

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            logger.debug(f"Loaded: {namespace}/{key}")
            return data

        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to load {namespace}/{key}: {e}")
            return None

    def delete(self, namespace: str, key: str) -> bool:
        """
        删除数据。

        Args:
            namespace: 命名空间
            key: 数据键

        Returns:
            是否删除成功
        """
        file_path = self._get_path(namespace, key)

        if not os.path.exists(file_path):
            return False

        try:
            os.remove(file_path)
            logger.info(f"Deleted: {namespace}/{key}")
            return True
        except OSError as e:
            logger.error(f"Failed to delete {namespace}/{key}: {e}")
            return False

    def exists(self, namespace: str, key: str) -> bool:
        """检查数据是否存在。"""
        return os.path.exists(self._get_path(namespace, key))

    def list_keys(self, namespace: str) -> list[str]:
        """
        列出命名空间下的所有键。

        Returns:
            键列表（不含 .json 后缀）
        """
        ns_dir = os.path.join(self.data_dir, namespace)

        if not os.path.exists(ns_dir):
            return []

        keys = []
        for filename in os.listdir(ns_dir):
            if filename.endswith(".json"):
                keys.append(filename[:-5])  # 去掉 .json 后缀

        return sorted(keys)

    def clear_namespace(self, namespace: str) -> int:
        """
        清空命名空间下的所有数据。

        Returns:
            被删除的文件数
        """
        ns_dir = os.path.join(self.data_dir, namespace)

        if not os.path.exists(ns_dir):
            return 0

        count = 0
        for filename in os.listdir(ns_dir):
            if filename.endswith(".json"):
                try:
                    os.remove(os.path.join(ns_dir, filename))
                    count += 1
                except OSError:
                    pass

        logger.info(f"Cleared namespace '{namespace}': {count} files")
        return count

    def get_storage_info(self) -> dict[str, Any]:
        """
        返回存储统计信息。

        Returns:
            包含各命名空间的文件数和总大小
        """
        info: dict[str, Any] = {
            "data_dir": self.data_dir,
            "namespaces": {},
            "total_files": 0,
            "total_size_bytes": 0,
        }

        if not os.path.exists(self.data_dir):
            return info

        for entry in os.listdir(self.data_dir):
            ns_path = os.path.join(self.data_dir, entry)
            if os.path.isdir(ns_path):
                files = [f for f in os.listdir(ns_path) if f.endswith(".json")]
                size = sum(
                    os.path.getsize(os.path.join(ns_path, f))
                    for f in files
                    if os.path.exists(os.path.join(ns_path, f))
                )
                info["namespaces"][entry] = {
                    "file_count": len(files),
                    "size_bytes": size,
                }
                info["total_files"] += len(files)
                info["total_size_bytes"] += size

        return info

    # ─────────────────────────────────────────────────────────────
    # 内部方法
    # ─────────────────────────────────────────────────────────────

    def _get_path(self, namespace: str, key: str) -> str:
        """生成文件路径。"""
        # 安全性：防止路径穿越
        safe_ns = namespace.replace("/", "_").replace("\\", "_").replace("..", "")
        safe_key = key.replace("/", "_").replace("\\", "_").replace("..", "")
        return os.path.join(self.data_dir, safe_ns, f"{safe_key}.json")
