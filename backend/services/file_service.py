"""
文件存储服务 — 用户文件空间管理。

功能:
- 上传/下载/删除文件 (用户隔离)
- 文本提取: PDF (PyPDF2) / DOCX (python-docx) / TXT / 图片 (Pillow, 仅元信息)
- 路径穿越防护 + 文件大小限制

Usage:
    service = FileService(base_dir="data/files")
    meta = service.save_file("U001", "report.pdf", pdf_bytes)
    meta, data = service.get_file("U001", meta.file_id)
    text = service.extract_text("U001", meta.file_id)
"""

from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import os
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

def _get_max_file_size() -> int:
    """Get max file size from settings, fallback to 100MB."""
    try:
        from config import settings
        return settings.max_file_upload_mb * 1024 * 1024
    except Exception:
        return 100 * 1024 * 1024

MAX_FILE_SIZE = _get_max_file_size()

# 允许的文件扩展名 (白名单)
ALLOWED_EXTENSIONS = {
    ".txt", ".csv", ".json", ".xml", ".yaml", ".yml", ".md",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp",
    ".zip", ".tar", ".gz",
    ".svg", ".html", ".jsx", ".tsx", ".py", ".js", ".ts", ".css", ".scss",
}

# 图片扩展名
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}

# Magic bytes → 扩展名映射 (用于验证文件内容与扩展名匹配)
_MAGIC_BYTES: list[tuple[bytes, set[str]]] = [
    (b"\x89PNG\r\n\x1a\n", {".png"}),
    (b"\xff\xd8\xff", {".jpg", ".jpeg"}),
    (b"GIF87a", {".gif"}),
    (b"GIF89a", {".gif"}),
    (b"%PDF", {".pdf"}),
    (b"PK\x03\x04", {".docx", ".xlsx", ".zip"}),  # ZIP-based formats
]


def _validate_magic_bytes(content: bytes, ext: str) -> None:
    """
    验证文件内容的 magic bytes 与声明的扩展名是否匹配。

    仅对有已知 magic bytes 的二进制格式做校验。
    文本类文件 (.txt, .csv, .json, .xml, .md, .yaml) 跳过检查。
    """
    # 文本类扩展名不检查 magic bytes
    text_exts = {".txt", ".csv", ".json", ".xml", ".yaml", ".yml", ".md"}
    if ext in text_exts:
        return

    # 检查是否有匹配的 magic bytes
    for magic, allowed_exts in _MAGIC_BYTES:
        if content[:len(magic)] == magic:
            if ext not in allowed_exts:
                raise ValueError(
                    f"File content doesn't match extension {ext}: "
                    f"detected format for {allowed_exts}"
                )
            return  # magic bytes 匹配且扩展名正确


@dataclass
class FileMetadata:
    """文件元数据"""
    file_id: str
    user_id: str
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    created_at: float
    extracted_text: str = ""
    session_id: str = ""


class FileService:
    """
    用户文件存储服务。

    目录结构:
        base_dir/
        ├── {user_id}/
        │   ├── {file_id}.{ext}         # 原始文件
        │   └── {file_id}.meta.json     # 元数据
    """

    def __init__(self, base_dir: str = "data/files") -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _sanitize_filename(self, filename: str) -> str:
        """清理文件名，防止路径穿越。"""
        # 移除路径分隔符
        name = os.path.basename(filename)
        # 移除特殊字符
        name = re.sub(r'[^\w.\-]', '_', name)
        # 限制长度
        if len(name) > 200:
            ext = Path(name).suffix
            name = name[:200 - len(ext)] + ext
        return name or "unnamed_file"

    def _user_dir(self, tenant_id: str, user_id: str) -> Path:
        """获取 tenant/user 目录，防止穿越。"""
        safe_tid = re.sub(r'[^\w\-]', '_', tenant_id)
        safe_uid = re.sub(r'[^\w\-]', '_', user_id)
        user_dir = self.base_dir / safe_tid / safe_uid
        # 验证路径在 base_dir 下
        resolved = user_dir.resolve()
        if not str(resolved).startswith(str(self.base_dir.resolve())):
            raise ValueError(f"Path traversal detected: {tenant_id}/{user_id}")
        return user_dir

    def save_file(
        self, tenant_id: str, user_id: str, filename: str, content: bytes,
        session_id: str = "",
    ) -> FileMetadata:
        """
        保存文件到用户空间。

        Args:
            user_id: 用户 ID
            filename: 原始文件名
            content: 文件内容 (bytes)

        Returns:
            FileMetadata

        Raises:
            ValueError: 文件过大 / 路径穿越 / 不支持的格式
        """
        # 1. 大小检查
        if len(content) > MAX_FILE_SIZE:
            raise ValueError(
                f"File too large: {len(content)} bytes "
                f"(max: {MAX_FILE_SIZE} bytes / {MAX_FILE_SIZE // 1024 // 1024}MB)"
            )

        # 2. 清理文件名
        safe_name = self._sanitize_filename(filename)
        ext = Path(safe_name).suffix.lower()

        # 3. 扩展名检查
        if not ext or ext not in ALLOWED_EXTENSIONS:
            raise ValueError(f"Unsupported file extension: {ext or '(none)'}")

        # 3b. Magic bytes 验证 — 防止伪造扩展名
        _validate_magic_bytes(content, ext)

        # 4. 创建用户目录
        user_dir = self._user_dir(tenant_id, user_id)
        user_dir.mkdir(parents=True, exist_ok=True)

        # 5. 生成 file_id
        file_id = str(uuid.uuid4())[:12]

        # 6. 计算 SHA256
        sha256 = hashlib.sha256(content).hexdigest()

        # 7. 推断 content_type
        content_type = mimetypes.guess_type(safe_name)[0] or "application/octet-stream"

        # 8. 保存文件
        file_ext = ext if ext else ""
        file_path = user_dir / f"{file_id}{file_ext}"
        file_path.write_bytes(content)

        # 9. 构建元数据
        metadata = FileMetadata(
            file_id=file_id,
            user_id=user_id,
            filename=safe_name,
            content_type=content_type,
            size_bytes=len(content),
            sha256=sha256,
            created_at=time.time(),
            session_id=session_id,
        )

        # 10. 保存元数据
        meta_path = user_dir / f"{file_id}.meta.json"
        meta_path.write_text(
            json.dumps(asdict(metadata), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        logger.info(
            f"File saved: {safe_name} ({len(content)} bytes) -> {file_id}",
            extra={"user_id": user_id, "file_id": file_id},
        )

        return metadata

    def get_file(
        self, tenant_id: str, user_id: str, file_id: str
    ) -> tuple[FileMetadata, bytes]:
        """
        获取文件。

        Returns:
            (FileMetadata, file_bytes)

        Raises:
            FileNotFoundError: 文件不存在
        """
        metadata = self._load_metadata(tenant_id, user_id, file_id)
        ext = Path(metadata.filename).suffix.lower()
        file_path = self._user_dir(tenant_id, user_id) / f"{file_id}{ext}"
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_id}")
        return metadata, file_path.read_bytes()

    def list_files(self, tenant_id: str, user_id: str) -> list[FileMetadata]:
        """列出用户所有文件。"""
        user_dir = self._user_dir(tenant_id, user_id)
        if not user_dir.exists():
            return []

        results = []
        for meta_file in sorted(user_dir.glob("*.meta.json")):
            try:
                data = json.loads(meta_file.read_text(encoding="utf-8"))
                results.append(FileMetadata(**data))
            except Exception as e:
                logger.warning(f"Failed to load metadata: {meta_file}: {e}")
        return results

    def list_files_by_session(self, tenant_id: str, user_id: str, session_id: str) -> list[FileMetadata]:
        """列出指定会话关联的文件。"""
        all_files = self.list_files(tenant_id, user_id)
        return [f for f in all_files if f.session_id == session_id]

    def delete_file(self, tenant_id: str, user_id: str, file_id: str) -> bool:
        """
        删除文件。

        Returns:
            True 表示成功删除, False 表示文件不存在
        """
        user_dir = self._user_dir(tenant_id, user_id)
        meta_path = user_dir / f"{file_id}.meta.json"

        if not meta_path.exists():
            return False

        try:
            metadata = self._load_metadata(tenant_id, user_id, file_id)
            ext = Path(metadata.filename).suffix.lower()
            file_path = user_dir / f"{file_id}{ext}"

            # 删除文件和元数据
            if file_path.exists():
                file_path.unlink()
            meta_path.unlink()

            logger.info(
                f"File deleted: {file_id}",
                extra={"user_id": user_id},
            )
            return True
        except Exception as e:
            logger.error(f"Failed to delete file {file_id}: {e}")
            return False

    def extract_text(self, tenant_id: str, user_id: str, file_id: str) -> str:
        """
        从文件提取文本。

        支持:
        - PDF (PyPDF2)
        - DOCX (python-docx)
        - TXT/CSV/JSON 等文本文件 (直接读取)
        - 图片 (返回尺寸信息)

        Returns:
            提取的文本内容
        """
        metadata, content = self.get_file(tenant_id, user_id, file_id)
        ext = Path(metadata.filename).suffix.lower()

        try:
            if ext == ".pdf":
                return self._extract_pdf(content)
            elif ext in (".docx", ".doc"):
                return self._extract_docx(content)
            elif ext in IMAGE_EXTENSIONS:
                return self._extract_image_info(content, metadata.filename)
            elif ext in (".txt", ".csv", ".json", ".xml", ".yaml", ".yml", ".md"):
                return self._extract_text_file(content)
            else:
                return (
                    f"[文件信息] {metadata.filename}\n"
                    f"类型: {metadata.content_type}\n"
                    f"大小: {metadata.size_bytes} bytes\n"
                    f"(不支持文本提取的文件格式: {ext})"
                )
        except Exception as e:
            logger.error(f"Text extraction failed for {file_id}: {e}")
            return (
                f"[文件信息] {metadata.filename}\n"
                f"类型: {metadata.content_type}\n"
                f"大小: {metadata.size_bytes} bytes\n"
                f"(文本提取失败: {e})"
            )

    def _load_metadata(self, tenant_id: str, user_id: str, file_id: str) -> FileMetadata:
        """加载文件元数据。"""
        user_dir = self._user_dir(tenant_id, user_id)
        meta_path = user_dir / f"{file_id}.meta.json"
        if not meta_path.exists():
            raise FileNotFoundError(f"File not found: {file_id}")
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        return FileMetadata(**data)

    def _extract_pdf(self, content: bytes) -> str:
        """从 PDF 提取文本。"""
        import io
        from PyPDF2 import PdfReader

        reader = PdfReader(io.BytesIO(content))
        pages = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            if text:
                pages.append(f"--- Page {i + 1} ---\n{text}")
        return "\n\n".join(pages) if pages else "(PDF 中未提取到文本)"

    def _extract_docx(self, content: bytes) -> str:
        """从 DOCX 提取文本。"""
        import io
        from docx import Document

        doc = Document(io.BytesIO(content))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n".join(paragraphs) if paragraphs else "(DOCX 中未提取到文本)"

    def _extract_image_info(self, content: bytes, filename: str) -> str:
        """从图片获取元信息。"""
        try:
            import io
            from PIL import Image

            img = Image.open(io.BytesIO(content))
            return (
                f"[图片文件] {filename}\n"
                f"格式: {img.format}\n"
                f"尺寸: {img.width} x {img.height} px\n"
                f"模式: {img.mode}\n"
                f"大小: {len(content)} bytes"
            )
        except Exception:
            return (
                f"[图片文件] {filename}\n"
                f"大小: {len(content)} bytes\n"
                f"(无法解析图片信息)"
            )

    def cleanup_expired(self, retention_days: int = 7) -> int:
        """清理过期的用户上传文件 (仅会话文件，不影响知识库和 workspace)。

        Args:
            retention_days: 保留天数，超过的文件将被删除

        Returns:
            删除的文件数量
        """
        if retention_days <= 0:
            return 0

        cutoff = time.time() - retention_days * 86400
        deleted = 0

        for meta_file in self.base_dir.rglob("*.meta.json"):
            try:
                data = json.loads(meta_file.read_text(encoding="utf-8"))
                created_at = data.get("created_at", 0)
                if created_at > 0 and created_at < cutoff:
                    # 删除原始文件
                    filename = data.get("filename", "")
                    file_id = data.get("file_id", "")
                    ext = Path(filename).suffix.lower() if filename else ""
                    file_path = meta_file.parent / f"{file_id}{ext}"
                    if file_path.exists():
                        file_path.unlink()
                    meta_file.unlink()
                    deleted += 1
                    logger.info(f"Expired file cleaned: {file_id} ({filename})")
            except Exception as e:
                logger.warning(f"Failed to check/clean {meta_file}: {e}")

        if deleted:
            logger.info(f"File cleanup: {deleted} expired files removed (>{retention_days} days)")
        return deleted

    def _extract_text_file(self, content: bytes) -> str:
        """读取文本文件。"""
        # 尝试 UTF-8 编码
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError:
            pass
        # 尝试 GBK 编码 (中文常见)
        try:
            return content.decode("gbk")
        except UnicodeDecodeError:
            pass
        # 最终回退
        return content.decode("utf-8", errors="replace")
