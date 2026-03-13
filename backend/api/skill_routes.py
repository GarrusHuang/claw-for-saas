"""
Skill 库管理 API。

提供 Skill CRUD + 导入，供前端 Skill 库页面使用。
"""
from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from core.auth import AuthUser, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/skills", tags=["skills"])


# ── 请求模型 ──

class SkillCreateRequest(BaseModel):
    name: str = Field(..., description="Skill 名称 (英文, 用作目录名)")
    description: str = Field("", description="Skill 描述")
    type: str = Field("domain", description="类型: domain/scenario/capability")
    version: str = Field("1.0", description="版本号")
    applies_to: list[str] = Field(default_factory=list, description="适用范围")
    business_types: list[str] = Field(default_factory=list, description="业务类型")
    depends_on: list[str] = Field(default_factory=list, description="依赖的其他 Skill")
    tags: list[str] = Field(default_factory=list, description="标签")
    token_estimate: int | None = Field(None, description="Token 估算")
    body: str = Field("", description="Skill 正文 (Markdown)")


class SkillImportRequest(BaseModel):
    content: str | None = Field(None, description="直接粘贴 SKILL.md 内容")
    url: str | None = Field(None, description="GitHub raw URL (将自动下载)")


# ── CRUD 端点 ──

@router.get("")
async def list_skills(_user: AuthUser = Depends(get_current_user)):
    """列出所有已注册的 Skills。"""
    from dependencies import get_skill_loader

    loader = get_skill_loader()
    skills = loader.list_skills()
    return {"skills": skills, "total": len(skills)}


@router.get("/{skill_name}")
async def get_skill_detail(skill_name: str, _user: AuthUser = Depends(get_current_user)):
    """获取单个 Skill 的元数据和正文。"""
    from dependencies import get_skill_loader

    loader = get_skill_loader()
    meta = loader.get_skill_metadata(skill_name)
    if not meta:
        return JSONResponse(status_code=404, content={"error": f"Skill '{skill_name}' not found"})

    body = loader._load_body(skill_name)
    return {"metadata": meta, "body": body}


@router.post("")
async def create_skill(req: SkillCreateRequest, _user: AuthUser = Depends(get_current_user)):
    """创建新 Skill。"""
    from dependencies import get_skill_loader

    loader = get_skill_loader()
    metadata = {
        "name": req.name,
        "description": req.description,
        "type": req.type,
        "version": req.version,
        "applies_to": req.applies_to,
        "business_types": req.business_types,
        "depends_on": req.depends_on,
        "tags": req.tags,
    }
    if req.token_estimate:
        metadata["token_estimate"] = req.token_estimate

    # Phase 18: Skill 验证
    from agent.skill_validator import SkillValidator
    existing = set(s.get("name", "") for s in loader.list_skills())
    validator = SkillValidator(existing_skill_names=existing)
    validation = validator.validate(metadata, req.body)
    if validation.status == "fail":
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "; ".join(validation.errors), "checks": validation.checks},
        )

    result = loader.create_skill(req.name, metadata, req.body)
    if not result["ok"]:
        return JSONResponse(status_code=400, content=result)

    # 附带警告信息
    if validation.warnings:
        result["warnings"] = validation.warnings
    return result


@router.put("/{skill_name}")
async def update_skill(skill_name: str, req: SkillCreateRequest, _user: AuthUser = Depends(get_current_user)):
    """更新已有 Skill。"""
    from dependencies import get_skill_loader

    loader = get_skill_loader()
    metadata = {
        "name": skill_name,
        "description": req.description,
        "type": req.type,
        "version": req.version,
        "applies_to": req.applies_to,
        "business_types": req.business_types,
        "depends_on": req.depends_on,
        "tags": req.tags,
    }
    if req.token_estimate:
        metadata["token_estimate"] = req.token_estimate

    result = loader.update_skill(skill_name, metadata, req.body)
    if not result["ok"]:
        return JSONResponse(status_code=400, content=result)
    return result


@router.delete("/{skill_name}")
async def delete_skill(skill_name: str, _user: AuthUser = Depends(get_current_user)):
    """删除 Skill。"""
    from dependencies import get_skill_loader

    loader = get_skill_loader()
    result = loader.delete_skill(skill_name)
    if not result["ok"]:
        status_code = 403 if "系统技能" in (result.get("error") or "") else 400
        return JSONResponse(status_code=status_code, content=result)
    return result


@router.post("/import")
async def import_skill(req: SkillImportRequest, _user: AuthUser = Depends(get_current_user)):
    """
    导入 Skill — 支持两种方式:
    1. content: 直接粘贴 SKILL.md 原始内容
    2. url: GitHub raw URL, 自动下载
    """
    from dependencies import get_skill_loader

    raw_content = req.content

    if not raw_content and req.url:
        # 将 GitHub 普通 URL 转为 raw URL
        url = req.url
        if "github.com" in url and "/blob/" in url:
            url = url.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                raw_content = resp.text
        except Exception as e:
            return JSONResponse(
                status_code=400,
                content={"ok": False, "error": f"Failed to fetch URL: {e}"},
            )

    if not raw_content:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "Provide either 'content' or 'url'"},
        )

    loader = get_skill_loader()

    # Phase 18: 导入前验证内容
    try:
        from agent.skill_validator import SkillValidator
        from skills.loader import _parse_frontmatter
        # 解析 frontmatter 用于验证
        import_meta, import_body = _parse_frontmatter(raw_content)
        existing = set(s.get("name", "") for s in loader.list_skills())
        validator = SkillValidator(existing_skill_names=existing)
        validation = validator.validate(import_meta, import_body)
        if validation.status == "fail":
            return JSONResponse(
                status_code=400,
                content={"ok": False, "error": "; ".join(validation.errors), "checks": validation.checks},
            )
    except Exception as e:
        logger.warning(f"Import validation skipped: {e}")

    result = loader.import_from_content(raw_content)
    if not result["ok"]:
        return JSONResponse(status_code=400, content=result)
    return result
