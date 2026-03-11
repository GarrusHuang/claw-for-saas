"""
文件管理 API 路由。

端点:
- POST /api/files/upload        — 上传文件
- GET  /api/files/              — 列出用户文件
- GET  /api/files/{file_id}     — 文件元数据
- GET  /api/files/{file_id}/text — 提取文本
- GET  /api/files/{file_id}/download — 下载文件
- DELETE /api/files/{file_id}   — 删除文件
"""

from __future__ import annotations

import logging
from urllib.parse import quote
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response

from core.auth import AuthUser, get_current_user
from dependencies import get_file_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/files", tags=["files"])


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    user: AuthUser = Depends(get_current_user),
):
    """上传文件到用户空间。"""
    service = get_file_service()

    try:
        content = await file.read()
        filename = file.filename or "unnamed"

        metadata = service.save_file(user.tenant_id, user.user_id, filename, content)

        return {
            "file_id": metadata.file_id,
            "filename": metadata.filename,
            "content_type": metadata.content_type,
            "size_bytes": metadata.size_bytes,
            "sha256": metadata.sha256,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Upload failed: {e}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {e}")


@router.get("/")
async def list_user_files(user: AuthUser = Depends(get_current_user)):
    """列出用户所有文件。"""
    service = get_file_service()

    files = service.list_files(user.tenant_id, user.user_id)
    return {
        "user_id": user.user_id,
        "files": [
            {
                "file_id": f.file_id,
                "filename": f.filename,
                "content_type": f.content_type,
                "size_bytes": f.size_bytes,
                "created_at": f.created_at,
            }
            for f in files
        ],
    }


@router.get("/{file_id}")
async def get_file_metadata(file_id: str, user: AuthUser = Depends(get_current_user)):
    """获取文件元数据。"""
    service = get_file_service()

    try:
        metadata, _ = service.get_file(user.tenant_id, user.user_id, file_id)
        return {
            "file_id": metadata.file_id,
            "filename": metadata.filename,
            "content_type": metadata.content_type,
            "size_bytes": metadata.size_bytes,
            "sha256": metadata.sha256,
            "created_at": metadata.created_at,
        }
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"File not found: {file_id}")


@router.get("/{file_id}/text")
async def get_extracted_text(file_id: str, user: AuthUser = Depends(get_current_user)):
    """提取文件文本内容。"""
    service = get_file_service()

    try:
        text = service.extract_text(user.tenant_id, user.user_id, file_id)
        return {
            "file_id": file_id,
            "text": text,
        }
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"File not found: {file_id}")


@router.get("/{file_id}/download")
async def download_file(file_id: str, user: AuthUser = Depends(get_current_user)):
    """下载文件（返回原始文件内容）。"""
    service = get_file_service()

    try:
        metadata, content = service.get_file(user.tenant_id, user.user_id, file_id)
        # RFC 5987: 中文文件名用 UTF-8 编码
        encoded_name = quote(metadata.filename)
        return Response(
            content=content,
            media_type=metadata.content_type or "application/octet-stream",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}",
                "Content-Length": str(len(content)),
            },
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"File not found: {file_id}")


@router.delete("/{file_id}")
async def delete_file(file_id: str, user: AuthUser = Depends(get_current_user)):
    """删除文件。"""
    service = get_file_service()

    deleted = service.delete_file(user.tenant_id, user.user_id, file_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"File not found: {file_id}")
    return {"status": "ok", "file_id": file_id}
