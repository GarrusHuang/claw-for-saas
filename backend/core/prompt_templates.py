"""
#27 Prompt Templates — 轻量级用户级常用指令保存/复用。

存储: data/prompt_templates/{tenant_id}/{user_id}.json
格式: {"templates": [{"name": "...", "content": "...", "created_at": "..."}]}
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_MAX_TEMPLATES_PER_USER = 50


class PromptTemplateStore:
    """用户级 Prompt 模板 CRUD。"""

    def __init__(self, base_dir: str = "data/prompt_templates") -> None:
        self._base_dir = base_dir

    def _path(self, tenant_id: str, user_id: str) -> str:
        return os.path.join(self._base_dir, tenant_id, f"{user_id}.json")

    def _load(self, tenant_id: str, user_id: str) -> list[dict]:
        path = self._path(tenant_id, user_id)
        if not os.path.exists(path):
            return []
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return data.get("templates", [])
        except (json.JSONDecodeError, OSError):
            return []

    def _save(self, tenant_id: str, user_id: str, templates: list[dict]) -> None:
        path = self._path(tenant_id, user_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"templates": templates}, f, ensure_ascii=False, indent=2)

    def list_templates(self, tenant_id: str, user_id: str) -> list[dict]:
        return self._load(tenant_id, user_id)

    def get_template(self, tenant_id: str, user_id: str, name: str) -> dict | None:
        for t in self._load(tenant_id, user_id):
            if t["name"] == name:
                return t
        return None

    def save_template(self, tenant_id: str, user_id: str, name: str, content: str) -> dict:
        templates = self._load(tenant_id, user_id)
        # 更新或创建
        for t in templates:
            if t["name"] == name:
                t["content"] = content
                t["updated_at"] = datetime.now(timezone.utc).isoformat()
                self._save(tenant_id, user_id, templates)
                return {"ok": True, "name": name, "action": "updated"}

        if len(templates) >= _MAX_TEMPLATES_PER_USER:
            return {"ok": False, "error": f"模板数量已达上限 ({_MAX_TEMPLATES_PER_USER})"}

        templates.append({
            "name": name,
            "content": content,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        self._save(tenant_id, user_id, templates)
        return {"ok": True, "name": name, "action": "created"}

    def delete_template(self, tenant_id: str, user_id: str, name: str) -> bool:
        templates = self._load(tenant_id, user_id)
        original_len = len(templates)
        templates = [t for t in templates if t["name"] != name]
        if len(templates) < original_len:
            self._save(tenant_id, user_id, templates)
            return True
        return False
