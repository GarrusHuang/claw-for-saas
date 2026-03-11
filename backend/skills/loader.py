"""
Skill 加载器 — A7 多源加载 + 优先级合并 + 大小预算。

A7 改造:
- 多源加载: builtin/ → plugins/ → tenant/ → user/ (优先级从低到高)
- 优先级合并: 同名 Skill 高优先级覆盖低优先级
- 大小预算: max_skills_prompt_chars + max_single_skill_chars

三级加载策略:
  L1 - 元数据注册表（启动时扫描 SKILL.md frontmatter）
  L2 - Skill 正文（首次使用时加载并缓存，注入 Agent System Prompt）
  L3 - 参考资料（按需读取，通过 skill_reference 工具暴露给 Agent）
"""

import os
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# backend/ 根目录
BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS_DIR = os.path.join(BACKEND_ROOT, "skills")

# A7: 标准子目录
BUILTIN_DIR = os.path.join(SKILLS_DIR, "builtin")
TENANT_DIR = os.path.join(SKILLS_DIR, "tenant")
USER_DIR = os.path.join(SKILLS_DIR, "user")

# A7: 优先级常量 (数值越大优先级越高)
PRIORITY_BUILTIN = 1
PRIORITY_PLUGIN = 2
PRIORITY_TENANT = 3
PRIORITY_USER = 4


def _parse_frontmatter(raw: str) -> tuple[dict, str]:
    """
    解析 SKILL.md 的 YAML frontmatter 和 markdown body。

    不依赖外部 YAML 库，仅处理简单 key: value 和 key: [list] 格式。

    Returns:
        (metadata_dict, body_text)
    """
    match = re.match(r"^---\s*\n(.*?\n)---\s*\n(.*)", raw, re.DOTALL)
    if not match:
        return {}, raw

    fm_text = match.group(1)
    body = match.group(2).strip()

    metadata: dict = {}
    for line in fm_text.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()

        # 去掉引号
        if (value.startswith('"') and value.endswith('"')) or \
           (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]

        # 解析 [item1, item2] 列表语法
        list_match = re.match(r"^\[(.*)\]$", value)
        if list_match:
            items = [
                item.strip().strip('"').strip("'")
                for item in list_match.group(1).split(",")
                if item.strip()
            ]
            metadata[key] = items
        else:
            if value.isdigit():
                metadata[key] = int(value)
            else:
                metadata[key] = value

    return metadata, body


class SkillLoader:
    """
    Skill 加载器 — A7 多源加载。

    多源加载 (优先级从低到高):
    1. builtin/  — Claw 自带 (PRIORITY_BUILTIN=1)
    2. plugins/  — 插件注册 (PRIORITY_PLUGIN=2)
    3. tenant/   — 租户自定义 (PRIORITY_TENANT=3)
    4. user/     — 用户自定义 (PRIORITY_USER=4)

    同名 Skill 高优先级覆盖低优先级。
    """

    def __init__(
        self,
        skills_dir: Optional[str] = None,
        max_prompt_chars: int = 30000,
        max_single_chars: int = 10000,
    ):
        self._skills_dir = skills_dir or SKILLS_DIR
        self._max_prompt_chars = max_prompt_chars  # A7: 总预算
        self._max_single_chars = max_single_chars  # A7: 单个上限

        # L1: name -> metadata dict (不含 body)
        self._registry: dict[str, dict] = {}
        # L2 cache: name -> body text
        self._body_cache: dict[str, str] = {}

        self._build_registry()

    # ------------------------------------------------------------------
    # L1 — 元数据注册表 (A7: 多源)
    # ------------------------------------------------------------------

    def _build_registry(self) -> None:
        """扫描多源 Skill 目录，构建 L1 注册表。"""
        # A7 标准目录结构: skills/builtin/ 优先
        builtin_dir = os.path.join(self._skills_dir, "builtin")
        if os.path.isdir(builtin_dir):
            self._scan_directory(builtin_dir, PRIORITY_BUILTIN)
        else:
            # 回退: 直接扫描 skills_dir 根目录 (兼容旧结构和测试)
            self._scan_directory(self._skills_dir, PRIORITY_BUILTIN)
        logger.info("Skill registry built: %d skills loaded", len(self._registry))

    def _scan_directory(self, base_dir: str, priority: int) -> int:
        """扫描一个目录下的所有 Skill，返回加载数量。"""
        if not os.path.isdir(base_dir):
            return 0

        count = 0
        for entry in os.listdir(base_dir):
            skill_dir = os.path.join(base_dir, entry)
            skill_file = os.path.join(skill_dir, "SKILL.md")
            if os.path.isdir(skill_dir) and os.path.isfile(skill_file):
                try:
                    with open(skill_file, "r", encoding="utf-8") as f:
                        raw = f.read()
                    metadata, _body = _parse_frontmatter(raw)
                    name = metadata.get("name", entry)
                    metadata.setdefault("name", name)
                    metadata["_dir"] = skill_dir
                    metadata["_priority"] = priority

                    # A7: 同名 Skill 高优先级覆盖低优先级
                    existing = self._registry.get(name)
                    if existing and existing.get("_priority", 0) >= priority:
                        logger.debug(
                            "Skipping skill %s (priority %d <= existing %d)",
                            name, priority, existing.get("_priority", 0),
                        )
                        continue

                    self._registry[name] = metadata
                    self._body_cache.pop(name, None)
                    count += 1
                    logger.info(
                        "Registered skill: %s (type=%s, priority=%d)",
                        name, metadata.get("type"), priority,
                    )
                except Exception:
                    logger.exception("Failed to parse skill: %s", skill_file)

        return count

    def load_tenant_skills(self, tenant_dir: str) -> int:
        """
        A7: 加载租户级 Skill。

        Args:
            tenant_dir: 租户 Skill 目录路径

        Returns:
            加载数量
        """
        count = self._scan_directory(tenant_dir, PRIORITY_TENANT)
        if count:
            logger.info("Loaded %d tenant skills from %s", count, tenant_dir)
        return count

    def load_user_skills(self, user_dir: str) -> int:
        """
        A7: 加载用户级 Skill。

        Args:
            user_dir: 用户 Skill 目录路径

        Returns:
            加载数量
        """
        count = self._scan_directory(user_dir, PRIORITY_USER)
        if count:
            logger.info("Loaded %d user skills from %s", count, user_dir)
        return count

    def register_plugin_skill(self, name: str, metadata: dict, body: str) -> None:
        """
        A7: 插件注册 Skill (通过 A5 PluginContext)。

        由 PluginContext.register_skill() 调用。
        """
        existing = self._registry.get(name)
        if existing and existing.get("_priority", 0) >= PRIORITY_PLUGIN:
            logger.debug("Skipping plugin skill %s (existing has higher priority)", name)
            return

        metadata["name"] = name
        metadata["_priority"] = PRIORITY_PLUGIN
        metadata["_plugin_body"] = body  # 插件 Skill body 直接存在 metadata 中
        self._registry[name] = metadata
        self._body_cache[name] = body
        logger.info("Registered plugin skill: %s", name)

    # ------------------------------------------------------------------
    # L2 — Skill 正文加载（带缓存）
    # ------------------------------------------------------------------

    def _load_body(self, skill_name: str) -> str:
        """按需加载并缓存 Skill body text。"""
        if skill_name in self._body_cache:
            return self._body_cache[skill_name]

        meta = self._registry.get(skill_name)
        if not meta:
            logger.warning("Skill not found in registry: %s", skill_name)
            return ""

        skill_file = os.path.join(meta["_dir"], "SKILL.md")
        try:
            with open(skill_file, "r", encoding="utf-8") as f:
                raw = f.read()
            _, body = _parse_frontmatter(raw)
            self._body_cache[skill_name] = body
            return body
        except Exception:
            logger.exception("Failed to load skill body: %s", skill_name)
            return ""

    def _resolve_depends(self, skill_name: str, visited: Optional[set] = None) -> list[str]:
        """递归解析依赖链，返回有序去重的依赖列表（依赖在前）。"""
        if visited is None:
            visited = set()
        if skill_name in visited:
            return []
        visited.add(skill_name)

        meta = self._registry.get(skill_name)
        if not meta:
            return []

        result: list[str] = []
        for dep in meta.get("depends_on", []):
            result.extend(self._resolve_depends(dep, visited))
        result.append(skill_name)
        return result

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_for_pipeline(
        self,
        scenario: Optional[str] = None,
        agent_name: Optional[str] = None,
        business_type: Optional[str] = None,
    ) -> str:
        """
        根据 pipeline 上下文匹配并加载 Skill 正文。

        A7 增强:
        - 按 _priority 排序（高优先级在后覆盖低优先级同名 Skill）
        - 大小预算控制: 超出 max_single_chars 的单个 Skill 被截断
        - 超出 max_prompt_chars 的低优先级 Skill 被丢弃
        """
        matched_names: list[str] = []

        for name, meta in self._registry.items():
            skill_type = meta.get("type", "capability")

            # 1) Scenario match
            if skill_type == "scenario" and scenario and name == scenario:
                matched_names.append(name)
                continue

            # 2) Capability match
            if skill_type == "capability":
                applies_to = meta.get("applies_to", [])
                if not applies_to or (agent_name and agent_name in applies_to):
                    matched_names.append(name)
                    continue

            # 3) Domain match
            if skill_type == "domain" and business_type:
                business_types = meta.get("business_types", [])
                applies_to = meta.get("applies_to", [])
                if business_type in business_types:
                    if not applies_to or (agent_name and agent_name in applies_to):
                        matched_names.append(name)
                    elif not agent_name:
                        matched_names.append(name)

        # 展开依赖（依赖在前），去重
        ordered: list[str] = []
        seen: set[str] = set()
        for name in matched_names:
            for resolved in self._resolve_depends(name):
                if resolved not in seen:
                    seen.add(resolved)
                    ordered.append(resolved)

        # A7: 按优先级排序（高优先级在前，预算裁剪时保留高优先级）
        ordered.sort(
            key=lambda n: self._registry.get(n, {}).get("_priority", 0),
            reverse=True,
        )

        # A7: 大小预算控制
        parts: list[str] = []
        total_chars = 0
        loaded_names: list[str] = []
        trimmed_names: list[str] = []

        for name in ordered:
            body = self._load_body(name)
            if not body:
                continue

            # 单个 Skill 截断
            if len(body) > self._max_single_chars:
                trailer = "\n\n[...Skill 内容被截断...]"
                body = body[:self._max_single_chars - len(trailer)] + trailer
                logger.info("Skill %s truncated (%d > %d chars)", name, len(body), self._max_single_chars)

            # 总预算检查
            if total_chars + len(body) > self._max_prompt_chars:
                trimmed_names.append(name)
                logger.info(
                    "Skill %s dropped (budget exceeded: %d + %d > %d)",
                    name, total_chars, len(body), self._max_prompt_chars,
                )
                continue

            parts.append(body)
            total_chars += len(body)
            loaded_names.append(name)

        if trimmed_names:
            logger.warning(
                "A7 budget: %d skills trimmed: %s", len(trimmed_names), trimmed_names
            )

        combined = "\n\n---\n\n".join(parts)
        if loaded_names:
            logger.info(
                "Loaded %d skills (%d chars) for pipeline (scenario=%s, agent=%s, biz=%s): %s",
                len(loaded_names), total_chars, scenario, agent_name, business_type, loaded_names,
            )
        return combined

    def read_reference(self, skill_name: str, ref_path: str) -> str:
        """L3 按需加载：读取 Skill 参考资料文件。"""
        meta = self._registry.get(skill_name)
        if not meta:
            return f"[ERROR] Skill not found: {skill_name}"

        full_path = os.path.join(meta["_dir"], "references", ref_path)

        # 安全检查：防止路径穿越
        real_base = os.path.realpath(meta["_dir"])
        real_path = os.path.realpath(full_path)
        if not real_path.startswith(real_base):
            return f"[ERROR] Invalid reference path: {ref_path}"

        if not os.path.isfile(full_path):
            return f"[ERROR] Reference file not found: {ref_path}"

        try:
            with open(full_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            logger.exception("Failed to read reference: %s/%s", skill_name, ref_path)
            return f"[ERROR] Failed to read reference: {e}"

    def list_skills(self) -> list[dict]:
        """返回所有 L1 元数据（用于管理 API）。"""
        result = []
        for name, meta in self._registry.items():
            public_meta = {k: v for k, v in meta.items() if not k.startswith("_")}
            public_meta["priority"] = meta.get("_priority", 0)
            result.append(public_meta)
        return result

    def get_skill_metadata(self, skill_name: str) -> Optional[dict]:
        """获取单个 Skill 的 L1 元数据。"""
        meta = self._registry.get(skill_name)
        if not meta:
            return None
        result = {k: v for k, v in meta.items() if not k.startswith("_")}
        result["priority"] = meta.get("_priority", 0)
        return result

    # ------------------------------------------------------------------
    # CRUD 操作
    # ------------------------------------------------------------------

    def _build_frontmatter(self, metadata: dict) -> str:
        """将 metadata dict 转为 YAML frontmatter 字符串。"""
        lines = ["---"]
        simple_keys = ["name", "version", "description", "type", "token_estimate"]
        list_keys = ["applies_to", "business_types", "depends_on", "tags"]

        for key in simple_keys:
            if key in metadata and metadata[key] is not None:
                val = metadata[key]
                if isinstance(val, str) and (":" in val or '"' in val):
                    lines.append(f'{key}: "{val}"')
                else:
                    lines.append(f"{key}: {val}")

        for key in list_keys:
            if key in metadata and metadata[key]:
                items = ", ".join(str(i) for i in metadata[key])
                lines.append(f"{key}: [{items}]")

        for key, val in metadata.items():
            if key not in simple_keys and key not in list_keys and not key.startswith("_"):
                if isinstance(val, list):
                    items = ", ".join(str(i) for i in val)
                    lines.append(f"{key}: [{items}]")
                else:
                    lines.append(f"{key}: {val}")

        lines.append("---")
        return "\n".join(lines)

    def create_skill(self, name: str, metadata: dict, body: str) -> dict:
        """创建新 Skill (默认创建到 builtin/ 子目录)。"""
        if name in self._registry:
            return {"ok": False, "error": f"Skill '{name}' already exists"}

        safe_name = name.replace("/", "_").replace("\\", "_").replace("..", "_")
        # A7: 优先创建到 builtin/ 子目录
        builtin_dir = os.path.join(self._skills_dir, "builtin")
        base = builtin_dir if os.path.isdir(builtin_dir) else self._skills_dir
        skill_dir = os.path.join(base, safe_name)

        try:
            os.makedirs(skill_dir, exist_ok=True)
            metadata["name"] = name
            frontmatter = self._build_frontmatter(metadata)
            content = f"{frontmatter}\n\n{body.strip()}\n"

            skill_file = os.path.join(skill_dir, "SKILL.md")
            with open(skill_file, "w", encoding="utf-8") as f:
                f.write(content)

            self._register_single(skill_dir)
            logger.info("Created skill: %s", name)
            return {"ok": True, "name": name}
        except Exception as e:
            logger.exception("Failed to create skill: %s", name)
            return {"ok": False, "error": str(e)}

    def update_skill(self, name: str, metadata: dict, body: str) -> dict:
        """更新已有 Skill 的 metadata 和 body。"""
        if name not in self._registry:
            return {"ok": False, "error": f"Skill '{name}' not found"}

        meta = self._registry[name]
        skill_file = os.path.join(meta["_dir"], "SKILL.md")

        try:
            metadata["name"] = name
            frontmatter = self._build_frontmatter(metadata)
            content = f"{frontmatter}\n\n{body.strip()}\n"

            with open(skill_file, "w", encoding="utf-8") as f:
                f.write(content)

            self._body_cache.pop(name, None)
            self._register_single(meta["_dir"])
            logger.info("Updated skill: %s", name)
            return {"ok": True, "name": name}
        except Exception as e:
            logger.exception("Failed to update skill: %s", name)
            return {"ok": False, "error": str(e)}

    def delete_skill(self, name: str) -> dict:
        """删除 Skill 目录和注册表条目。"""
        if name not in self._registry:
            return {"ok": False, "error": f"Skill '{name}' not found"}

        import shutil
        meta = self._registry[name]
        skill_dir = meta["_dir"]

        try:
            shutil.rmtree(skill_dir)
            del self._registry[name]
            self._body_cache.pop(name, None)
            logger.info("Deleted skill: %s", name)
            return {"ok": True, "name": name}
        except Exception as e:
            logger.exception("Failed to delete skill: %s", name)
            return {"ok": False, "error": str(e)}

    def import_from_content(self, raw_content: str) -> dict:
        """从原始 SKILL.md 内容导入 Skill。"""
        metadata, body = _parse_frontmatter(raw_content)
        name = metadata.get("name")
        if not name:
            return {"ok": False, "error": "SKILL.md must have 'name' in frontmatter"}

        if name in self._registry:
            return {"ok": False, "error": f"Skill '{name}' already exists, use update instead"}

        safe_name = name.replace("/", "_").replace("\\", "_").replace("..", "_")
        builtin_dir = os.path.join(self._skills_dir, "builtin")
        base = builtin_dir if os.path.isdir(builtin_dir) else self._skills_dir
        skill_dir = os.path.join(base, safe_name)

        try:
            os.makedirs(skill_dir, exist_ok=True)
            skill_file = os.path.join(skill_dir, "SKILL.md")
            with open(skill_file, "w", encoding="utf-8") as f:
                f.write(raw_content)

            self._register_single(skill_dir)
            logger.info("Imported skill: %s", name)
            return {"ok": True, "name": name}
        except Exception as e:
            logger.exception("Failed to import skill: %s", name)
            return {"ok": False, "error": str(e)}

    def _register_single(self, skill_dir: str, priority: int = PRIORITY_BUILTIN) -> None:
        """注册/刷新单个 Skill 目录。"""
        skill_file = os.path.join(skill_dir, "SKILL.md")
        if not os.path.isfile(skill_file):
            return
        try:
            with open(skill_file, "r", encoding="utf-8") as f:
                raw = f.read()
            metadata, _body = _parse_frontmatter(raw)
            name = metadata.get("name", os.path.basename(skill_dir))
            metadata.setdefault("name", name)
            metadata["_dir"] = skill_dir
            metadata["_priority"] = priority
            self._registry[name] = metadata
            self._body_cache.pop(name, None)
        except Exception:
            logger.exception("Failed to register skill: %s", skill_file)
