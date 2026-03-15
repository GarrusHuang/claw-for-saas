"""知识库 API 路由。"""
from __future__ import annotations
import asyncio
import logging
from fastapi import APIRouter, Depends, UploadFile, File, Form
from fastapi.responses import JSONResponse, Response
from core.auth import AuthUser, get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


async def _auto_index(service, meta, tenant_id: str, user_id: str) -> None:
    """上传后自动生成摘要并更新 _index.md。"""
    try:
        # 提取文本（限前 5000 字符）
        text = service.extract_text(meta.file_id)
        if not text or not text.strip():
            return
        snippet = text[:5000]

        # 调 LLM 生成摘要
        from core.llm_client import LLMGatewayClient, LLMClientConfig
        from config import settings

        llm = LLMGatewayClient(config=LLMClientConfig(
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            api_key=settings.llm_api_key,
        ))
        resp = await llm.chat_completion(
            messages=[
                {"role": "system", "content": "你是一个文档摘要助手。根据文件内容生成 2-3 句话的中文摘要（不超过 200 字），说明文件是什么、包含什么关键内容、什么场景下有用。只输出摘要文本，不要加标题或格式。"},
                {"role": "user", "content": f"文件名: {meta.filename}\n\n内容:\n{snippet}"},
            ],
            max_tokens=300,
            temperature=0.3,
        )
        summary = (resp.content or "").strip()
        if not summary:
            return

        # 更新 _index.md
        index_paths = service.get_index_paths(tenant_id, user_id)
        scope_idx = 0 if meta.scope == "global" else 1
        index_path = index_paths[scope_idx]
        index_path.parent.mkdir(parents=True, exist_ok=True)

        if index_path.exists():
            existing = index_path.read_text(encoding="utf-8")
        else:
            existing = "# 知识库索引\n\n以下是知识库中的文件摘要。需要引用具体内容时，使用 read_knowledge_file(file_id) 工具按需读取全文。\n"

        new_entry = f"\n## {meta.file_id}: {meta.filename}\n{summary}\n"
        index_path.write_text(existing + new_entry, encoding="utf-8")

        # 同步更新 meta description
        import json
        meta_path = next(service.base_dir.rglob(f"{meta.file_id}.meta.json"), None)
        if meta_path:
            from dataclasses import asdict
            meta_data = asdict(meta)
            meta_data["description"] = summary[:200]
            meta_path.write_text(json.dumps(meta_data, ensure_ascii=False, indent=2), encoding="utf-8")

        logger.info(f"KB index updated for {meta.file_id}: {meta.filename}")
    except Exception as e:
        logger.warning(f"Auto-index failed for {meta.file_id}: {e}")

def _get_service():
    from dependencies import get_knowledge_service
    return get_knowledge_service()

@router.post("/upload")
async def upload_knowledge_file(
    file: UploadFile = File(...),
    scope: str = Form("user"),
    description: str = Form(""),
    user: AuthUser = Depends(get_current_user),
):
    """上传知识文件。"""
    service = _get_service()
    content = await file.read()
    is_admin = "admin" in getattr(user, "roles", [])
    try:
        meta = service.add_file(
            tenant_id=user.tenant_id, user_id=user.user_id,
            filename=file.filename or "unnamed", content=content,
            scope=scope, description=description, is_admin=is_admin,
        )
    except PermissionError as e:
        return JSONResponse(status_code=403, content={"error": str(e)})
    # 后台异步生成摘要索引
    asyncio.create_task(_auto_index(service, meta, user.tenant_id, user.user_id))
    from dataclasses import asdict
    return asdict(meta)

@router.get("/")
async def list_knowledge_files(user: AuthUser = Depends(get_current_user)):
    """列出知识文件 (全局 + 用户)。"""
    service = _get_service()
    from dataclasses import asdict
    files = service.list_files(user.tenant_id, user.user_id)
    return {"files": [asdict(f) for f in files], "total": len(files)}

@router.get("/{file_id}")
async def get_knowledge_file_meta(file_id: str, _user: AuthUser = Depends(get_current_user)):
    """获取知识文件元数据。"""
    service = _get_service()
    meta = service.get_file_meta(file_id)
    if not meta:
        return JSONResponse(status_code=404, content={"error": "File not found"})
    from dataclasses import asdict
    return asdict(meta)

@router.get("/{file_id}/download")
async def download_knowledge_file(file_id: str, _user: AuthUser = Depends(get_current_user)):
    """下载知识文件。"""
    service = _get_service()
    result = service.get_file(file_id)
    if not result:
        return JSONResponse(status_code=404, content={"error": "File not found"})
    meta, content = result
    from urllib.parse import quote
    encoded = quote(meta.filename, safe='')
    return Response(
        content=content, media_type=meta.content_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"},
    )

@router.get("/{file_id}/preview")
async def preview_knowledge_file(file_id: str, _user: AuthUser = Depends(get_current_user)):
    """返回知识文件的结构化预览数据。"""
    service = _get_service()
    result = service.get_file(file_id)
    if not result:
        return JSONResponse(status_code=404, content={"error": "File not found"})
    meta, content = result

    from pathlib import Path
    ext = Path(meta.filename).suffix.lower()
    base_url = f"/api/knowledge/{file_id}"

    # Image
    # SVG — 效果预览 + 源码双模式
    if ext == '.svg':
        try:
            source = content.decode('utf-8')
        except UnicodeDecodeError:
            source = content.decode('utf-8', errors='replace')
        return {"type": "svg", "source": source, "url": f"{base_url}/download", "filename": meta.filename}

    if ext in ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp'):
        return {"type": "image", "url": f"{base_url}/download", "filename": meta.filename}

    # PDF
    if ext == '.pdf':
        return {"type": "pdf", "url": f"{base_url}/download", "filename": meta.filename}

    # DOCX — 前端用 docx-preview 渲染原始文件
    if ext in ('.docx', '.doc'):
        return {"type": "docx", "url": f"{base_url}/download", "filename": meta.filename}

    # Excel
    if ext in ('.xlsx', '.xls'):
        try:
            from api.file_routes import _extract_excel
            sheets = _extract_excel(content)
            return {"type": "excel", "sheets": sheets, "filename": meta.filename}
        except Exception as e:
            return {"type": "text", "content": f"[Excel 解析失败: {e}]", "filename": meta.filename}

    # HTML
    if ext == '.html':
        try:
            source = content.decode('utf-8')
        except UnicodeDecodeError:
            source = content.decode('utf-8', errors='replace')
        return {"type": "html", "source": source, "render_url": f"{base_url}/render", "filename": meta.filename}

    # Code files
    code_exts = {
        '.py': 'python', '.js': 'javascript', '.ts': 'typescript',
        '.jsx': 'jsx', '.tsx': 'tsx', '.css': 'css', '.scss': 'scss',
        '.java': 'java', '.go': 'go', '.rs': 'rust', '.c': 'c',
        '.cpp': 'cpp', '.h': 'c', '.rb': 'ruby', '.php': 'php',
        '.sh': 'bash', '.sql': 'sql', '.yaml': 'yaml', '.yml': 'yaml',
        '.xml': 'xml', '.svg': 'xml',
    }
    if ext in code_exts:
        try:
            text = content.decode('utf-8')
        except UnicodeDecodeError:
            text = content.decode('utf-8', errors='replace')
        return {"type": "code", "content": text, "language": code_exts[ext], "filename": meta.filename}

    # Markdown
    if ext == '.md':
        try:
            text = content.decode('utf-8')
        except UnicodeDecodeError:
            text = content.decode('utf-8', errors='replace')
        return {"type": "markdown", "content": text, "filename": meta.filename}

    # Plain text
    if ext in ('.txt', '.csv', '.json', '.log', '.ini', '.conf'):
        try:
            text = content.decode('utf-8')
        except UnicodeDecodeError:
            try:
                text = content.decode('gbk')
            except UnicodeDecodeError:
                text = content.decode('utf-8', errors='replace')
        lang = 'json' if ext == '.json' else 'csv' if ext == '.csv' else ''
        return {"type": "code" if lang else "text", "content": text, "language": lang, "filename": meta.filename}

    # Fallback
    return {
        "type": "unsupported",
        "filename": meta.filename,
        "content_type": meta.content_type,
        "size_bytes": meta.size_bytes,
    }


@router.get("/{file_id}/render")
async def render_knowledge_file(file_id: str, _user: AuthUser = Depends(get_current_user)):
    """原样返回 HTML 知识文件 (用于 iframe 加载)。"""
    service = _get_service()
    result = service.get_file(file_id)
    if not result:
        return JSONResponse(status_code=404, content={"error": "File not found"})
    _, content = result
    return Response(content=content, media_type="text/html")


@router.get("/{file_id}/text")
async def get_knowledge_file_text(file_id: str, _user: AuthUser = Depends(get_current_user)):
    """提取知识文件文本。"""
    service = _get_service()
    text = service.extract_text(file_id)
    return {"file_id": file_id, "text": text}

@router.delete("/{file_id}")
async def delete_knowledge_file(file_id: str, user: AuthUser = Depends(get_current_user)):
    """删除知识文件 (仅所有者)。"""
    service = _get_service()
    try:
        ok = service.delete_file(user.tenant_id, user.user_id, file_id)
        if not ok:
            return JSONResponse(status_code=404, content={"error": "File not found"})
        # 从 _index.md 中移除条目
        try:
            import re as _re
            for index_path in service.get_index_paths(user.tenant_id, user.user_id):
                if index_path.exists():
                    content = index_path.read_text(encoding="utf-8")
                    # 移除 ## {file_id}: ... 段落（到下一个 ## 或文件末尾）
                    pattern = _re.compile(
                        rf"(\n?)## {_re.escape(file_id)}:.*?(?=\n## |\Z)",
                        _re.DOTALL,
                    )
                    new_content = pattern.sub("", content)
                    if new_content != content:
                        index_path.write_text(new_content, encoding="utf-8")
                        logger.info(f"KB index entry removed for {file_id}")
        except Exception as e:
            logger.warning(f"Failed to remove index entry for {file_id}: {e}")
        return {"status": "ok", "file_id": file_id}
    except PermissionError as e:
        return JSONResponse(status_code=403, content={"error": str(e)})
