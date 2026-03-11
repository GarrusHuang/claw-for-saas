"""
文件操作能力工具。

通过 contextvars 获取 FileService 和 user_id，
Agent 可读取用户上传的文件、列出文件、分析文件结构。

所有工具为 read_only=True（不修改文件系统）。
"""

from __future__ import annotations

import logging

from core.context import current_event_bus, current_user_id, current_tenant_id
from core.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)

file_capability_registry = ToolRegistry()


def _get_file_service():
    """从 contextvars 获取 FileService。"""
    from core.context import current_file_service
    service = current_file_service.get()
    if service is None:
        raise RuntimeError("FileService not available (not injected)")
    return service


@file_capability_registry.tool(
    description=(
        "读取用户上传的文件内容。"
        "传入 file_id (从 list_user_files 获取)，返回文件的提取文本。"
        "支持 PDF/DOCX/TXT/CSV/JSON 等格式的文本提取。"
        "图片文件返回尺寸等元信息。"
    ),
    read_only=True,
)
def read_uploaded_file(file_id: str) -> dict:  # 文件 ID
    """读取用户上传的文件，返回提取的文本内容。"""
    service = _get_file_service()
    tenant_id = current_tenant_id.get()
    user_id = current_user_id.get()

    try:
        text = service.extract_text(tenant_id, user_id, file_id)
        metadata, _ = service.get_file(tenant_id, user_id, file_id)
        return {
            "file_id": file_id,
            "filename": metadata.filename,
            "content_type": metadata.content_type,
            "size_bytes": metadata.size_bytes,
            "text": text,
        }
    except FileNotFoundError:
        return {"error": f"File not found: {file_id}"}
    except Exception as e:
        logger.error(f"read_uploaded_file error: {e}")
        return {"error": str(e)}


@file_capability_registry.tool(
    description=(
        "列出当前用户上传的所有文件。"
        "返回文件列表，包含 file_id/filename/content_type/size_bytes。"
        "使用 file_id 可调用 read_uploaded_file 读取文件内容。"
    ),
    read_only=True,
)
def list_user_files() -> dict:
    """列出当前用户的所有文件。"""
    service = _get_file_service()
    tenant_id = current_tenant_id.get()
    user_id = current_user_id.get()

    try:
        files = service.list_files(tenant_id, user_id)
        return {
            "user_id": user_id,
            "file_count": len(files),
            "files": [
                {
                    "file_id": f.file_id,
                    "filename": f.filename,
                    "content_type": f.content_type,
                    "size_bytes": f.size_bytes,
                }
                for f in files
            ],
        }
    except Exception as e:
        logger.error(f"list_user_files error: {e}")
        return {"error": str(e)}


@file_capability_registry.tool(
    description=(
        "分析用户上传文件的结构和基本信息。"
        "返回文件的详细元信息：大小、类型、页数(PDF)、行数(文本)等。"
    ),
    read_only=True,
)
def analyze_file(file_id: str) -> dict:  # 文件 ID
    """分析文件结构，返回详细元信息。"""
    service = _get_file_service()
    tenant_id = current_tenant_id.get()
    user_id = current_user_id.get()

    try:
        metadata, content = service.get_file(tenant_id, user_id, file_id)
        ext = metadata.filename.rsplit(".", 1)[-1].lower() if "." in metadata.filename else ""

        analysis = {
            "file_id": file_id,
            "filename": metadata.filename,
            "content_type": metadata.content_type,
            "size_bytes": metadata.size_bytes,
            "sha256": metadata.sha256,
        }

        # 按类型补充分析
        if ext == "pdf":
            try:
                import io
                from PyPDF2 import PdfReader
                reader = PdfReader(io.BytesIO(content))
                analysis["page_count"] = len(reader.pages)
                analysis["format"] = "PDF"
            except Exception:
                analysis["format"] = "PDF (parse error)"

        elif ext in ("docx", "doc"):
            try:
                import io
                from docx import Document
                doc = Document(io.BytesIO(content))
                analysis["paragraph_count"] = len(doc.paragraphs)
                analysis["table_count"] = len(doc.tables)
                analysis["format"] = "DOCX"
            except Exception:
                analysis["format"] = "DOCX (parse error)"

        elif ext in ("txt", "csv", "json", "xml", "yaml", "yml", "md"):
            try:
                text = content.decode("utf-8", errors="replace")
                lines = text.split("\n")
                analysis["line_count"] = len(lines)
                analysis["char_count"] = len(text)
                analysis["format"] = ext.upper()
            except Exception:
                analysis["format"] = f"{ext.upper()} (parse error)"

        elif ext in ("png", "jpg", "jpeg", "gif", "bmp", "webp"):
            try:
                import io
                from PIL import Image
                img = Image.open(io.BytesIO(content))
                analysis["width"] = img.width
                analysis["height"] = img.height
                analysis["image_mode"] = img.mode
                analysis["image_format"] = img.format
                analysis["format"] = "Image"
            except Exception:
                analysis["format"] = "Image (parse error)"
        else:
            analysis["format"] = ext.upper() or "Unknown"

        return analysis

    except FileNotFoundError:
        return {"error": f"File not found: {file_id}"}
    except Exception as e:
        logger.error(f"analyze_file error: {e}")
        return {"error": str(e)}
