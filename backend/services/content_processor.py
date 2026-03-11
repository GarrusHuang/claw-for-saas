"""
多模态内容处理器 (A4: 4i)。

根据文件 MIME 类型选择合适的处理策略:
- 文本文件: 直接返回文本
- PDF: 提取文本 (PyMuPDF/pdfplumber) → 分页返回
- 图片: 转 base64 (可选压缩) → 返回 image_url 格式
- 不支持的格式: 返回文件元信息 + 提示
"""

from __future__ import annotations

import base64
import io
import logging
import mimetypes
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# 支持的图片格式
IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "bmp"}
# 支持的文本格式
TEXT_EXTENSIONS = {"txt", "csv", "json", "xml", "yaml", "yml", "md", "log", "ini", "conf", "py", "js", "ts", "html", "css"}
# PDF
PDF_EXTENSIONS = {"pdf"}


@dataclass
class ProcessedContent:
    """处理后的内容"""
    content_type: str  # "text" | "image" | "unsupported"
    text: str | None = None
    image_base64: str | None = None
    image_media_type: str | None = None  # "image/png" etc
    metadata: dict | None = None
    error: str | None = None


def detect_type(filename: str) -> str:
    """检测文件类型分类。返回 'text' | 'image' | 'pdf' | 'unsupported'。"""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in TEXT_EXTENSIONS:
        return "text"
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in PDF_EXTENSIONS:
        return "pdf"
    if ext in ("docx", "doc"):
        return "text"  # 通过 python-docx 提取文本
    return "unsupported"


def process_image(
    content: bytes,
    filename: str,
    max_dimension: int = 1024,
) -> ProcessedContent:
    """
    处理图片文件: 可选压缩 → 转 base64。

    Args:
        content: 原始文件字节
        filename: 文件名
        max_dimension: 最大边长 (超过则缩放)

    Returns:
        ProcessedContent with image_base64
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "png"
    media_type = mimetypes.guess_type(filename)[0] or f"image/{ext}"

    metadata = {
        "original_size_bytes": len(content),
        "format": ext.upper(),
    }

    try:
        # 尝试用 PIL 处理 (可选压缩)
        from PIL import Image
        img = Image.open(io.BytesIO(content))
        metadata["width"] = img.width
        metadata["height"] = img.height
        metadata["mode"] = img.mode

        # 大图压缩
        if max(img.width, img.height) > max_dimension:
            img.thumbnail((max_dimension, max_dimension), Image.LANCZOS)
            metadata["resized_to"] = f"{img.width}x{img.height}"
            buf = io.BytesIO()
            save_format = "JPEG" if ext in ("jpg", "jpeg") else "PNG"
            img.save(buf, format=save_format, quality=85)
            content = buf.getvalue()
            metadata["compressed_size_bytes"] = len(content)

    except ImportError:
        logger.debug("PIL not available, using raw image bytes")
    except Exception as e:
        logger.warning(f"Image processing failed for {filename}: {e}")

    b64 = base64.b64encode(content).decode("ascii")

    return ProcessedContent(
        content_type="image",
        image_base64=b64,
        image_media_type=media_type,
        metadata=metadata,
    )


def process_pdf(
    content: bytes,
    filename: str,
    max_pages: int = 50,
) -> ProcessedContent:
    """
    处理 PDF 文件: 提取文本。

    优先用 PyMuPDF (fitz)，fallback 到 PyPDF2。
    """
    metadata = {
        "original_size_bytes": len(content),
        "format": "PDF",
    }

    # 尝试 PyMuPDF
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=content, filetype="pdf")
        metadata["page_count"] = len(doc)
        pages_to_read = min(len(doc), max_pages)
        text_parts = []
        for i in range(pages_to_read):
            page_text = doc[i].get_text()
            text_parts.append(f"--- Page {i+1} ---\n{page_text}")
        doc.close()

        if pages_to_read < metadata["page_count"]:
            text_parts.append(
                f"\n[... {metadata['page_count'] - pages_to_read} more pages not extracted ...]"
            )

        return ProcessedContent(
            content_type="text",
            text="\n".join(text_parts),
            metadata=metadata,
        )
    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"PyMuPDF failed for {filename}: {e}")

    # Fallback: PyPDF2
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(io.BytesIO(content))
        metadata["page_count"] = len(reader.pages)
        pages_to_read = min(len(reader.pages), max_pages)
        text_parts = []
        for i in range(pages_to_read):
            page_text = reader.pages[i].extract_text() or ""
            text_parts.append(f"--- Page {i+1} ---\n{page_text}")

        if pages_to_read < metadata["page_count"]:
            text_parts.append(
                f"\n[... {metadata['page_count'] - pages_to_read} more pages not extracted ...]"
            )

        return ProcessedContent(
            content_type="text",
            text="\n".join(text_parts),
            metadata=metadata,
        )
    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"PyPDF2 failed for {filename}: {e}")

    return ProcessedContent(
        content_type="unsupported",
        metadata=metadata,
        error="PDF extraction failed: no PDF library available (install PyMuPDF or PyPDF2)",
    )


def process_file(
    content: bytes,
    filename: str,
    max_image_dimension: int = 1024,
    max_pdf_pages: int = 50,
) -> ProcessedContent:
    """
    统一入口: 根据文件类型分发到对应处理器。

    Args:
        content: 文件字节
        filename: 文件名
        max_image_dimension: 图片最大边长
        max_pdf_pages: PDF 最大提取页数

    Returns:
        ProcessedContent
    """
    file_type = detect_type(filename)

    if file_type == "image":
        return process_image(content, filename, max_dimension=max_image_dimension)

    if file_type == "pdf":
        return process_pdf(content, filename, max_pages=max_pdf_pages)

    if file_type == "text":
        # 文本类直接解码
        try:
            text = content.decode("utf-8", errors="replace")
            return ProcessedContent(
                content_type="text",
                text=text,
                metadata={"format": filename.rsplit(".", 1)[-1].upper(), "char_count": len(text)},
            )
        except Exception as e:
            return ProcessedContent(
                content_type="unsupported",
                error=f"Text decode failed: {e}",
            )

    # 不支持的格式
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "unknown"
    return ProcessedContent(
        content_type="unsupported",
        metadata={"format": ext.upper(), "size_bytes": len(content)},
        error=f"Unsupported format: {ext}. Supported: text, PDF, images ({', '.join(IMAGE_EXTENSIONS)})",
    )
