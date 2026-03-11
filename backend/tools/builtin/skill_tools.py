"""
Skill 管理能力工具 — 让 Agent 在对话中创建/更新 Skill。

通过 contextvars 获取 SkillLoader 和 EventBus。
配合 skill-creator 元技能使用。
"""

from __future__ import annotations

from core.context import current_event_bus, current_skill_loader
from core.tool_registry import ToolRegistry

skill_capability_registry = ToolRegistry()


@skill_capability_registry.tool(
    description=(
        "创建新的 Skill。在与用户协作完成 Skill 设计后，调用此工具将 Skill 写入系统。\n"
        "name: Skill 名称 (小写字母+连字符，如 'invoice-processing')\n"
        "description: Skill 描述 (说明什么场景下触发)\n"
        "skill_type: Skill 类型 — domain(领域知识) / scenario(场景策略) / capability(能力增强)\n"
        "body: Skill 正文 (Markdown 格式，包含指导和知识)\n"
        "applies_to: 适用的 Agent (默认 ['universal'])\n"
        "business_types: 适用的业务类型 (如 ['reimbursement', 'contract'])\n"
        "depends_on: 依赖的其他 Skill 名称列表\n"
        "tags: 标签列表\n"
        "token_estimate: 预估 token 数"
    ),
    read_only=False,
)
def create_skill(
    name: str,  # Skill 名称 (小写+连字符)
    description: str,  # Skill 描述
    skill_type: str,  # domain / scenario / capability
    body: str,  # Markdown 正文
    applies_to: list | None = None,  # 适用 Agent ['universal']
    business_types: list | None = None,  # 适用业务类型
    depends_on: list | None = None,  # 依赖 Skill 列表
    tags: list | None = None,  # 标签
    token_estimate: int | None = None,  # 预估 token
) -> dict:
    """创建新 Skill 并注册到系统。"""
    loader = current_skill_loader.get()
    if not loader:
        return {"status": "error", "message": "SkillLoader not available"}

    metadata = {
        "name": name,
        "description": description,
        "type": skill_type,
        "version": "1.0",
        "applies_to": applies_to or ["universal"],
        "business_types": business_types or [],
        "depends_on": depends_on or [],
        "tags": tags or [],
    }
    if token_estimate:
        metadata["token_estimate"] = token_estimate

    result = loader.create_skill(name, metadata, body)

    # 通过 SSE 通知前端
    bus = current_event_bus.get()
    if bus and result.get("ok"):
        bus.emit("skill_created", {
            "name": name,
            "type": skill_type,
            "description": description,
        })

    if result.get("ok"):
        return {
            "status": "ok",
            "message": f"Skill '{name}' 已成功创建并注册到系统。",
            "name": name,
        }
    else:
        return {
            "status": "error",
            "message": result.get("error", "Unknown error"),
        }


@skill_capability_registry.tool(
    description=(
        "更新已有的 Skill。修改 Skill 的描述、正文或元数据。\n"
        "name: 要更新的 Skill 名称\n"
        "其他参数同 create_skill，只需传入要修改的字段。"
    ),
    read_only=False,
)
def update_skill(
    name: str,  # 要更新的 Skill 名称
    description: str = "",  # 新描述
    skill_type: str = "",  # 新类型
    body: str = "",  # 新正文
    applies_to: list | None = None,
    business_types: list | None = None,
    depends_on: list | None = None,
    tags: list | None = None,
    token_estimate: int | None = None,
) -> dict:
    """更新已有 Skill 的内容和元数据。"""
    loader = current_skill_loader.get()
    if not loader:
        return {"status": "error", "message": "SkillLoader not available"}

    # 获取现有 metadata
    existing = loader.get_skill_metadata(name)
    if not existing:
        return {"status": "error", "message": f"Skill '{name}' not found"}

    # 合并更新
    metadata = dict(existing)
    if description:
        metadata["description"] = description
    if skill_type:
        metadata["type"] = skill_type
    if applies_to is not None:
        metadata["applies_to"] = applies_to
    if business_types is not None:
        metadata["business_types"] = business_types
    if depends_on is not None:
        metadata["depends_on"] = depends_on
    if tags is not None:
        metadata["tags"] = tags
    if token_estimate is not None:
        metadata["token_estimate"] = token_estimate

    # 如果没有传 body，加载现有 body
    if not body:
        body = loader._load_body(name)

    result = loader.update_skill(name, metadata, body)

    bus = current_event_bus.get()
    if bus and result.get("ok"):
        bus.emit("skill_updated", {"name": name})

    if result.get("ok"):
        return {
            "status": "ok",
            "message": f"Skill '{name}' 已更新。",
            "name": name,
        }
    else:
        return {
            "status": "error",
            "message": result.get("error", "Unknown error"),
        }
