"""
Skill 加载器。

启动时扫描 skills/ 目录构建注册表。
支持三级加载策略：
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


def _parse_frontmatter(raw: str) -> tuple[dict, str]:
    """
    解析 SKILL.md 的 YAML frontmatter 和 markdown body。

    不依赖外部 YAML 库，仅处理简单 key: value 和 key: [list] 格式。

    Returns:
        (metadata_dict, body_text)
    """
    # 分离 frontmatter 和 body
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
            # 尝试将纯数字转为 int
            if value.isdigit():
                metadata[key] = int(value)
            else:
                metadata[key] = value

    return metadata, body


class SkillLoader:
    """
    Skill 加载器。

    启动时扫描 skills/ 目录构建注册表。

    Core methods:
    - _build_registry(): Scan all SKILL.md, parse YAML frontmatter -> L1 metadata registry
    - load_for_pipeline(scenario, agent_name, business_type) -> str:
        Returns matched Skill body text (L2) for injection into Agent System Prompt
        Matching logic:
        1. Scenario Skill (match by scenario) -> auto-load depends_on recursively
        2. Capability Skill (match agent_name in applies_to)
        3. Domain Skill (match business_type)
        Deduplicate and merge, return combined text
    - read_reference(skill_name, ref_path) -> str:
        L3 on-demand loading, exposed as Agent tool (skill_reference tool)
    - list_skills() -> list[dict]:
        Returns all L1 metadata (for management API)
    """

    def __init__(self, skills_dir: Optional[str] = None):
        self._skills_dir = skills_dir or SKILLS_DIR
        # L1: name -> metadata dict (不含 body)
        self._registry: dict[str, dict] = {}
        # L2 cache: name -> body text
        self._body_cache: dict[str, str] = {}

        self._build_registry()

    # ------------------------------------------------------------------
    # L1 — 元数据注册表
    # ------------------------------------------------------------------

    def _build_registry(self) -> None:
        """扫描 skills/ 下所有 SKILL.md，解析 frontmatter 构建 L1 注册表。"""
        if not os.path.isdir(self._skills_dir):
            logger.warning("Skills directory not found: %s", self._skills_dir)
            return

        for entry in os.listdir(self._skills_dir):
            skill_dir = os.path.join(self._skills_dir, entry)
            skill_file = os.path.join(skill_dir, "SKILL.md")
            if os.path.isdir(skill_dir) and os.path.isfile(skill_file):
                try:
                    with open(skill_file, "r", encoding="utf-8") as f:
                        raw = f.read()
                    metadata, _body = _parse_frontmatter(raw)
                    name = metadata.get("name", entry)
                    metadata.setdefault("name", name)
                    metadata["_dir"] = skill_dir
                    self._registry[name] = metadata
                    logger.info("Registered skill: %s (type=%s)", name, metadata.get("type"))
                except Exception:
                    logger.exception("Failed to parse skill: %s", skill_file)

        logger.info("Skill registry built: %d skills loaded", len(self._registry))

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

        匹配逻辑（按优先级）：
        1. Scenario Skill — type=scenario 且 name 匹配 scenario 参数，
           自动递归加载 depends_on
        2. Capability Skill — type=capability 且 agent_name 在 applies_to 中
        3. Domain Skill — type=domain 且 business_type 在 business_types 中，
           且 agent_name 在 applies_to 中（如提供了 agent_name）

        去重合并后返回完整文本。
        """
        matched_names: list[str] = []

        for name, meta in self._registry.items():
            skill_type = meta.get("type", "capability")  # fallback for Anthropic official format

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
                    # 空 applies_to 匹配所有 agent，否则检查 agent_name
                    if not applies_to or (agent_name and agent_name in applies_to):
                        matched_names.append(name)
                    elif not agent_name:
                        matched_names.append(name)

        # 展开依赖（依赖在前），并去重
        ordered: list[str] = []
        seen: set[str] = set()
        for name in matched_names:
            for resolved in self._resolve_depends(name):
                if resolved not in seen:
                    seen.add(resolved)
                    ordered.append(resolved)

        # 拼接 body
        parts: list[str] = []
        for name in ordered:
            body = self._load_body(name)
            if body:
                parts.append(body)

        combined = "\n\n---\n\n".join(parts)
        if ordered:
            logger.info(
                "Loaded %d skills for pipeline (scenario=%s, agent=%s, biz=%s): %s",
                len(ordered), scenario, agent_name, business_type, ordered,
            )
        return combined

    def read_reference(self, skill_name: str, ref_path: str) -> str:
        """
        L3 按需加载：读取 Skill 参考资料文件。

        文件路径: skills/{skill_name}/references/{ref_path}
        暴露为 Agent tool (skill_reference)。
        """
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
            # 排除内部字段
            public_meta = {k: v for k, v in meta.items() if not k.startswith("_")}
            result.append(public_meta)
        return result

    def get_skill_metadata(self, skill_name: str) -> Optional[dict]:
        """获取单个 Skill 的 L1 元数据。"""
        meta = self._registry.get(skill_name)
        if not meta:
            return None
        return {k: v for k, v in meta.items() if not k.startswith("_")}

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

        # 保留其他 key
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
        """
        创建新 Skill。

        写入 skills/{name}/SKILL.md 并刷新注册表。
        返回 {"ok": True, "name": name} 或 {"ok": False, "error": "..."}
        """
        if name in self._registry:
            return {"ok": False, "error": f"Skill '{name}' already exists"}

        # 安全检查
        safe_name = name.replace("/", "_").replace("\\", "_").replace("..", "_")
        skill_dir = os.path.join(self._skills_dir, safe_name)

        try:
            os.makedirs(skill_dir, exist_ok=True)
            metadata["name"] = name
            frontmatter = self._build_frontmatter(metadata)
            content = f"{frontmatter}\n\n{body.strip()}\n"

            skill_file = os.path.join(skill_dir, "SKILL.md")
            with open(skill_file, "w", encoding="utf-8") as f:
                f.write(content)

            # 刷新注册表
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

            # 清缓存 + 重新注册
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
        """
        从原始 SKILL.md 内容导入 Skill。

        解析 frontmatter 提取 name，创建目录并写入。
        """
        metadata, body = _parse_frontmatter(raw_content)
        name = metadata.get("name")
        if not name:
            return {"ok": False, "error": "SKILL.md must have 'name' in frontmatter"}

        if name in self._registry:
            return {"ok": False, "error": f"Skill '{name}' already exists, use update instead"}

        safe_name = name.replace("/", "_").replace("\\", "_").replace("..", "_")
        skill_dir = os.path.join(self._skills_dir, safe_name)

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

    def _register_single(self, skill_dir: str) -> None:
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
            self._registry[name] = metadata
            self._body_cache.pop(name, None)
        except Exception:
            logger.exception("Failed to register skill: %s", skill_file)

