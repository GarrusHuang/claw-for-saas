"""
Agent 角色定义系统 — Phase 16。

从 agents/*.md 加载角色定义 (YAML frontmatter + Markdown body)。
每个角色包含:
- 系统提示词 (Markdown body)
- 工具白名单 (allowed_tools)
- 运行参数 (max_iterations, temperature)

Usage:
    loader = AgentRoleLoader(Path("agents"))
    role = loader.load_role("data-validator")
    print(role.allowed_tools)  # ["calculator_add", ...]
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AgentRole:
    """Agent 角色定义"""
    name: str
    description: str
    system_prompt: str  # Markdown body
    allowed_tools: list[str] = field(default_factory=list)
    max_iterations: int = 8
    temperature: float | None = None


class AgentRoleLoader:
    """
    从 agents/*.md 加载角色定义。

    文件格式:
    ```
    ---
    name: data-validator
    description: 数据验证员
    allowed_tools:
      - numeric_compare
      - sum_values
    max_iterations: 8
    temperature: 0.3
    ---

    你是一个专业的数据验证员...
    ```
    """

    def __init__(self, agents_dir: Path | str) -> None:
        self.agents_dir = Path(agents_dir)
        self._cache: dict[str, AgentRole] = {}

    def load_role(self, role_name: str) -> AgentRole:
        """
        加载指定角色定义。

        Args:
            role_name: 角色名称 (对应 agents/{role_name}.md)

        Returns:
            AgentRole

        Raises:
            ValueError: 角色不存在
        """
        # 缓存命中
        if role_name in self._cache:
            return self._cache[role_name]

        # 查找文件
        md_path = self.agents_dir / f"{role_name}.md"
        if not md_path.exists():
            raise ValueError(
                f"Agent role '{role_name}' not found. "
                f"Expected file: {md_path}. "
                f"Available roles: {self.list_roles()}"
            )

        # 解析文件
        content = md_path.read_text(encoding="utf-8")
        metadata, body = self._parse_frontmatter(content)

        role = AgentRole(
            name=metadata.get("name", role_name),
            description=metadata.get("description", ""),
            system_prompt=body.strip(),
            allowed_tools=metadata.get("allowed_tools", []),
            max_iterations=int(metadata.get("max_iterations", 8)),
            temperature=float(metadata["temperature"]) if "temperature" in metadata else None,
        )

        self._cache[role_name] = role
        logger.info(f"Loaded agent role: {role_name} ({len(role.allowed_tools)} tools)")
        return role

    def list_roles(self) -> list[str]:
        """列出所有可用角色名称。"""
        if not self.agents_dir.exists():
            return []
        return sorted(
            p.stem for p in self.agents_dir.glob("*.md")
            if not p.name.startswith("_")
        )

    def _parse_frontmatter(self, content: str) -> tuple[dict, str]:
        """
        解析 YAML frontmatter + Markdown body。

        简易 YAML 解析 (不依赖 PyYAML):
        - key: value  → 字符串
        - key: 数字    → 自动转换
        - key:\\n  - item1\\n  - item2  → 列表
        """
        # 分离 frontmatter 和 body
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)", content, re.DOTALL)
        if not match:
            return {}, content

        yaml_text = match.group(1)
        body = match.group(2)

        metadata = self._simple_yaml_parse(yaml_text)
        return metadata, body

    def _simple_yaml_parse(self, yaml_text: str) -> dict:
        """简易 YAML 解析器 (不依赖外部库)。"""
        result: dict[str, Any] = {}
        current_key: str | None = None
        current_list: list[str] | None = None

        for line in yaml_text.split("\n"):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            # 列表项: "  - value"
            if stripped.startswith("- ") and current_key is not None:
                if current_list is None:
                    current_list = []
                current_list.append(stripped[2:].strip())
                result[current_key] = current_list
                continue

            # 键值对: "key: value"
            if ":" in stripped:
                # 保存上一个列表
                current_list = None

                key, _, value = stripped.partition(":")
                key = key.strip()
                value = value.strip()

                current_key = key

                if value:
                    # 尝试数字转换
                    try:
                        if "." in value:
                            result[key] = float(value)
                        else:
                            result[key] = int(value)
                    except ValueError:
                        # 布尔值
                        if value.lower() in ("true", "yes"):
                            result[key] = True
                        elif value.lower() in ("false", "no"):
                            result[key] = False
                        else:
                            result[key] = value
                # value 为空说明可能跟着列表

        return result
