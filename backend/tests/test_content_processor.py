"""
Comprehensive tests for ContentProcessor (A4-4i Multimodal).

Covers:
- process_image(): PNG/JPEG/GIF, metadata, resizing, PIL fallback, corrupted/empty input
- process_pdf(): valid PDF, text extraction, max_pages, library fallbacks, corrupted/empty input
- process_file(): edge cases (empty, large text, binary, param forwarding, special filenames)
- detect_type(): uppercase/mixed-case extensions, all supported formats
"""
import base64
import io
import struct
import sys
import os
import zlib
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.content_processor import (
    IMAGE_EXTENSIONS,
    PDF_EXTENSIONS,
    TEXT_EXTENSIONS,
    ProcessedContent,
    detect_type,
    process_file,
    process_image,
    process_pdf,
)


# ════════════════════════════════════════════════════════
# Helpers: minimal valid file constructors
# ════════════════════════════════════════════════════════


def _make_png(width: int = 1, height: int = 1) -> bytes:
    """Create a minimal valid PNG image (RGB, 8-bit)."""
    sig = b"\x89PNG\r\n\x1a\n"
    # IHDR: width, height, bit_depth=8, color_type=2 (RGB), compression=0, filter=0, interlace=0
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ihdr_crc = zlib.crc32(b"IHDR" + ihdr_data) & 0xFFFFFFFF
    ihdr = struct.pack(">I", 13) + b"IHDR" + ihdr_data + struct.pack(">I", ihdr_crc)
    # IDAT: each row is filter_byte(0) + 3 bytes per pixel (RGB)
    raw_rows = b""
    for _ in range(height):
        raw_rows += b"\x00" + b"\xff\x00\x00" * width  # red pixels
    compressed = zlib.compress(raw_rows)
    idat_crc = zlib.crc32(b"IDAT" + compressed) & 0xFFFFFFFF
    idat = struct.pack(">I", len(compressed)) + b"IDAT" + compressed + struct.pack(">I", idat_crc)
    # IEND
    iend_crc = zlib.crc32(b"IEND") & 0xFFFFFFFF
    iend = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", iend_crc)
    return sig + ihdr + idat + iend


def _make_jpeg() -> bytes:
    """Create a minimal valid JPEG using PIL."""
    from PIL import Image

    img = Image.new("RGB", (2, 2), color=(255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _make_gif() -> bytes:
    """Create a minimal valid GIF using PIL."""
    from PIL import Image

    img = Image.new("P", (2, 2), color=0)
    buf = io.BytesIO()
    img.save(buf, format="GIF")
    return buf.getvalue()


def _make_bmp() -> bytes:
    """Create a minimal valid BMP using PIL."""
    from PIL import Image

    img = Image.new("RGB", (2, 2), color=(0, 255, 0))
    buf = io.BytesIO()
    img.save(buf, format="BMP")
    return buf.getvalue()


def _make_pdf(pages: int = 1) -> bytes:
    """Create a minimal valid PDF with given page count using PyMuPDF."""
    import fitz

    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page(width=200, height=200)
        page.insert_text((10, 50), f"Page {i + 1} content here")
    buf = doc.tobytes()
    doc.close()
    return buf


def _make_large_png(width: int, height: int) -> bytes:
    """Create a valid PNG of specified dimensions using PIL."""
    from PIL import Image

    img = Image.new("RGB", (width, height), color=(0, 128, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ════════════════════════════════════════════════════════
# 1. process_image() Direct Tests
# ════════════════════════════════════════════════════════


class TestProcessImagePNG:
    """Test process_image with valid PNG bytes."""

    def test_valid_png_returns_image_type(self):
        png = _make_png()
        result = process_image(png, "test.png")
        assert result.content_type == "image"

    def test_valid_png_has_base64(self):
        png = _make_png()
        result = process_image(png, "test.png")
        assert result.image_base64 is not None
        assert len(result.image_base64) > 0

    def test_valid_png_media_type(self):
        png = _make_png()
        result = process_image(png, "test.png")
        assert result.image_media_type == "image/png"

    def test_valid_png_metadata_dimensions(self):
        png = _make_png(width=1, height=1)
        result = process_image(png, "test.png")
        assert result.metadata["width"] == 1
        assert result.metadata["height"] == 1

    def test_valid_png_metadata_mode(self):
        png = _make_png()
        result = process_image(png, "test.png")
        assert result.metadata["mode"] == "RGB"

    def test_valid_png_metadata_format(self):
        png = _make_png()
        result = process_image(png, "test.png")
        assert result.metadata["format"] == "PNG"

    def test_valid_png_metadata_original_size(self):
        png = _make_png()
        result = process_image(png, "test.png")
        assert result.metadata["original_size_bytes"] == len(png)

    def test_base64_roundtrip(self):
        """Decoded base64 should produce a valid image."""
        png = _make_png()
        result = process_image(png, "test.png")
        decoded = base64.b64decode(result.image_base64)
        # For a 1x1 PNG that doesn't trigger resizing, decoded == original
        assert len(decoded) > 0
        # Verify it starts with PNG signature
        assert decoded[:4] == b"\x89PNG"


class TestProcessImageJPEG:
    """Test process_image with valid JPEG bytes."""

    def test_valid_jpeg_returns_image_type(self):
        jpg = _make_jpeg()
        result = process_image(jpg, "photo.jpg")
        assert result.content_type == "image"

    def test_valid_jpeg_media_type(self):
        jpg = _make_jpeg()
        result = process_image(jpg, "photo.jpg")
        assert result.image_media_type == "image/jpeg"

    def test_valid_jpeg_metadata(self):
        jpg = _make_jpeg()
        result = process_image(jpg, "photo.jpg")
        assert result.metadata["width"] == 2
        assert result.metadata["height"] == 2
        assert result.metadata["format"] == "JPG"

    def test_jpeg_extension_alternate(self):
        """'.jpeg' extension should also work."""
        jpg = _make_jpeg()
        result = process_image(jpg, "photo.jpeg")
        assert result.content_type == "image"
        assert result.metadata["format"] == "JPEG"


class TestProcessImageGIF:
    """Test process_image with valid GIF bytes."""

    def test_valid_gif_returns_image_type(self):
        gif = _make_gif()
        result = process_image(gif, "anim.gif")
        assert result.content_type == "image"

    def test_valid_gif_media_type(self):
        gif = _make_gif()
        result = process_image(gif, "anim.gif")
        assert result.image_media_type == "image/gif"

    def test_valid_gif_metadata(self):
        gif = _make_gif()
        result = process_image(gif, "anim.gif")
        assert result.metadata["width"] == 2
        assert result.metadata["height"] == 2


class TestProcessImageBMP:
    """Test process_image with valid BMP bytes."""

    def test_valid_bmp_returns_image_type(self):
        bmp = _make_bmp()
        result = process_image(bmp, "img.bmp")
        assert result.content_type == "image"

    def test_valid_bmp_media_type(self):
        bmp = _make_bmp()
        result = process_image(bmp, "img.bmp")
        assert result.image_media_type == "image/x-ms-bmp" or "bmp" in result.image_media_type.lower()


class TestProcessImageResizing:
    """Test resizing behavior with max_dimension parameter."""

    def test_small_image_not_resized(self):
        """Image smaller than max_dimension should not be resized."""
        png = _make_large_png(100, 100)
        result = process_image(png, "small.png", max_dimension=1024)
        assert "resized_to" not in result.metadata

    def test_large_image_triggers_resize(self):
        """Image larger than max_dimension should be thumbnailed."""
        png = _make_large_png(2048, 1536)
        result = process_image(png, "large.png", max_dimension=1024)
        assert "resized_to" in result.metadata
        assert "compressed_size_bytes" in result.metadata

    def test_custom_max_dimension_512(self):
        """Custom max_dimension=512 should resize accordingly."""
        png = _make_large_png(800, 600)
        result = process_image(png, "mid.png", max_dimension=512)
        assert "resized_to" in result.metadata
        # After thumbnail, both dims should be <= 512
        resized = result.metadata["resized_to"]
        w, h = map(int, resized.split("x"))
        assert w <= 512
        assert h <= 512

    def test_large_image_compressed_size_smaller(self):
        """Compressed size should be less than or comparable to original for large images."""
        png = _make_large_png(2048, 2048)
        result = process_image(png, "huge.png", max_dimension=512)
        assert result.metadata["compressed_size_bytes"] < result.metadata["original_size_bytes"]

    def test_exact_max_dimension_not_resized(self):
        """Image with max dim exactly at max_dimension should not be resized."""
        png = _make_large_png(1024, 768)
        result = process_image(png, "exact.png", max_dimension=1024)
        assert "resized_to" not in result.metadata

    def test_jpeg_resize_saves_as_jpeg(self):
        """JPEG images should be re-saved as JPEG after resize."""
        from PIL import Image

        img = Image.new("RGB", (2048, 2048), color=(128, 64, 32))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        jpg_bytes = buf.getvalue()

        result = process_image(jpg_bytes, "big.jpg", max_dimension=512)
        assert "resized_to" in result.metadata
        # Verify the output is still valid JPEG by decoding and checking
        decoded = base64.b64decode(result.image_base64)
        assert decoded[:2] == b"\xff\xd8"  # JPEG magic bytes


class TestProcessImagePILUnavailable:
    """Test fallback when PIL is not available."""

    def test_pil_import_error_returns_raw_base64(self):
        """When PIL raises ImportError, should fall back to raw base64."""
        content = b"\x89PNG\r\n\x1a\nfake_image_data"
        with patch.dict("sys.modules", {"PIL": None, "PIL.Image": None}):
            result = process_image(content, "test.png")
        assert result.content_type == "image"
        assert result.image_base64 is not None
        # Should not have PIL-derived metadata
        assert "width" not in result.metadata
        assert "height" not in result.metadata
        assert "mode" not in result.metadata
        # Should still have basic metadata
        assert result.metadata["original_size_bytes"] == len(content)
        assert result.metadata["format"] == "PNG"

    def test_pil_import_error_base64_correct(self):
        """Base64 of raw bytes should be correct even without PIL."""
        content = b"raw_binary_data_for_testing"
        with patch.dict("sys.modules", {"PIL": None, "PIL.Image": None}):
            result = process_image(content, "img.png")
        decoded = base64.b64decode(result.image_base64)
        assert decoded == content


class TestProcessImageCorruptedInput:
    """Test process_image with corrupted or malformed bytes."""

    def test_corrupted_image_does_not_crash(self):
        """Corrupted image bytes should not raise an exception."""
        corrupted = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50 + b"GARBAGE"
        result = process_image(corrupted, "broken.png")
        assert result.content_type == "image"
        # Should still produce base64 (raw fallback on PIL error)
        assert result.image_base64 is not None

    def test_random_bytes_does_not_crash(self):
        """Completely random bytes should not crash."""
        random_bytes = bytes(range(256)) * 4
        result = process_image(random_bytes, "random.png")
        assert result.content_type == "image"
        assert result.image_base64 is not None

    def test_zero_byte_image_does_not_crash(self):
        """Empty (0-byte) content should be handled gracefully."""
        result = process_image(b"", "empty.png")
        assert result.content_type == "image"
        assert result.image_base64 is not None
        # base64 of empty bytes is empty string
        assert result.image_base64 == ""
        assert result.metadata["original_size_bytes"] == 0

    def test_base64_encoding_correctness(self):
        """Verify base64 result decodes back to original for non-resized image."""
        content = b"arbitrary_binary_content_12345"
        # Use PIL unavailable to guarantee no transformation
        with patch.dict("sys.modules", {"PIL": None, "PIL.Image": None}):
            result = process_image(content, "test.png")
        decoded = base64.b64decode(result.image_base64)
        assert decoded == content


# ════════════════════════════════════════════════════════
# 2. process_pdf() Direct Tests
# ════════════════════════════════════════════════════════


class TestProcessPdfValid:
    """Test process_pdf with valid PDF bytes."""

    def test_valid_pdf_returns_text_type(self):
        pdf = _make_pdf(pages=1)
        result = process_pdf(pdf, "doc.pdf")
        assert result.content_type == "text"

    def test_text_extraction_content(self):
        pdf = _make_pdf(pages=1)
        result = process_pdf(pdf, "doc.pdf")
        assert "Page 1" in result.text
        assert "content here" in result.text

    def test_page_count_metadata(self):
        pdf = _make_pdf(pages=3)
        result = process_pdf(pdf, "doc.pdf")
        assert result.metadata["page_count"] == 3

    def test_multi_page_extraction(self):
        pdf = _make_pdf(pages=3)
        result = process_pdf(pdf, "doc.pdf")
        assert "Page 1" in result.text
        assert "Page 2" in result.text
        assert "Page 3" in result.text

    def test_original_size_in_metadata(self):
        pdf = _make_pdf(pages=1)
        result = process_pdf(pdf, "doc.pdf")
        assert result.metadata["original_size_bytes"] == len(pdf)
        assert result.metadata["format"] == "PDF"


class TestProcessPdfMaxPages:
    """Test max_pages truncation behavior."""

    def test_max_pages_limits_extraction(self):
        pdf = _make_pdf(pages=5)
        result = process_pdf(pdf, "doc.pdf", max_pages=2)
        assert result.metadata["page_count"] == 5
        assert "Page 1" in result.text
        assert "Page 2" in result.text
        # Page 3-5 should NOT be extracted
        assert "Page 3 content" not in result.text

    def test_max_pages_truncation_message(self):
        """When max_pages < actual pages, a truncation message should appear."""
        pdf = _make_pdf(pages=5)
        result = process_pdf(pdf, "doc.pdf", max_pages=2)
        assert "3 more pages not extracted" in result.text

    def test_max_pages_equal_to_page_count(self):
        """max_pages == page_count should extract all without truncation message."""
        pdf = _make_pdf(pages=3)
        result = process_pdf(pdf, "doc.pdf", max_pages=3)
        assert "more pages not extracted" not in result.text
        assert "Page 3" in result.text

    def test_max_pages_greater_than_page_count(self):
        """max_pages > page_count should extract all without error."""
        pdf = _make_pdf(pages=2)
        result = process_pdf(pdf, "doc.pdf", max_pages=100)
        assert result.metadata["page_count"] == 2
        assert "more pages not extracted" not in result.text

    def test_max_pages_one(self):
        """max_pages=1 on multi-page PDF."""
        pdf = _make_pdf(pages=4)
        result = process_pdf(pdf, "doc.pdf", max_pages=1)
        assert "Page 1" in result.text
        assert "3 more pages not extracted" in result.text


class TestProcessPdfLibraryFallbacks:
    """Test PDF library fallback behavior."""

    def test_pymupdf_unavailable_falls_to_pypdf2(self):
        """When fitz is unavailable, should fall back to PyPDF2."""
        pdf = _make_pdf(pages=1)
        with patch.dict("sys.modules", {"fitz": None}):
            result = process_pdf(pdf, "doc.pdf")
        assert result.content_type == "text"
        assert "Page 1" in result.text

    def test_both_libraries_unavailable(self):
        """When both fitz and PyPDF2 are unavailable, should return unsupported."""
        pdf = _make_pdf(pages=1)
        with patch.dict("sys.modules", {"fitz": None, "PyPDF2": None, "PyPDF2.PdfReader": None}):
            result = process_pdf(pdf, "doc.pdf")
        assert result.content_type == "unsupported"
        assert result.error is not None
        assert "no PDF library" in result.error

    def test_both_unavailable_still_has_metadata(self):
        """Even when both libs fail, metadata should contain size and format."""
        content = b"%PDF-1.4 fake"
        with patch.dict("sys.modules", {"fitz": None, "PyPDF2": None, "PyPDF2.PdfReader": None}):
            result = process_pdf(content, "doc.pdf")
        assert result.metadata["original_size_bytes"] == len(content)
        assert result.metadata["format"] == "PDF"


class TestProcessPdfCorrupted:
    """Test process_pdf with corrupted or problematic input."""

    def test_corrupted_pdf_does_not_crash(self):
        """Corrupted PDF bytes should not raise an exception."""
        corrupted = b"%PDF-1.4 this is totally not a real pdf"
        result = process_pdf(corrupted, "broken.pdf")
        # Should either extract something or return unsupported, but not crash
        assert result.content_type in ("text", "unsupported")

    def test_zero_byte_pdf(self):
        """Empty (0-byte) PDF content should be handled gracefully."""
        result = process_pdf(b"", "empty.pdf")
        assert result.content_type in ("text", "unsupported")
        assert result.metadata["original_size_bytes"] == 0

    def test_random_bytes_as_pdf(self):
        """Random bytes should not crash."""
        result = process_pdf(b"\x00\x01\x02\x03\x04\x05", "random.pdf")
        assert result.content_type in ("text", "unsupported")

    def test_empty_pdf_valid_but_no_text(self):
        """A valid PDF with no text content."""
        import fitz

        doc = fitz.open()
        doc.new_page(width=100, height=100)  # empty page, no text
        pdf_bytes = doc.tobytes()
        doc.close()

        result = process_pdf(pdf_bytes, "blank.pdf")
        assert result.content_type == "text"
        assert result.metadata["page_count"] == 1
        # Text should be minimal (just the page header)
        assert "Page 1" in result.text


# ════════════════════════════════════════════════════════
# 3. process_file() Edge Cases
# ════════════════════════════════════════════════════════


class TestProcessFileEmpty:
    """Test process_file with empty (0-byte) content for each type."""

    def test_empty_text_file(self):
        result = process_file(b"", "empty.txt")
        assert result.content_type == "text"
        assert result.text == ""
        assert result.metadata["char_count"] == 0

    def test_empty_image_file(self):
        result = process_file(b"", "empty.png")
        assert result.content_type == "image"
        assert result.image_base64 is not None

    def test_empty_pdf_file(self):
        result = process_file(b"", "empty.pdf")
        assert result.content_type in ("text", "unsupported")

    def test_empty_unsupported_file(self):
        result = process_file(b"", "empty.zip")
        assert result.content_type == "unsupported"
        assert result.metadata["size_bytes"] == 0


class TestProcessFileLargeText:
    """Test process_file with large text content."""

    def test_large_text_file_complete(self):
        """Large text file should be fully decoded."""
        large_text = "A" * 500_000
        result = process_file(large_text.encode("utf-8"), "big.txt")
        assert result.content_type == "text"
        assert result.metadata["char_count"] == 500_000
        assert len(result.text) == 500_000

    def test_text_metadata_format(self):
        result = process_file(b"hello", "data.csv")
        assert result.metadata["format"] == "CSV"


class TestProcessFileBinaryAsText:
    """Test text path with binary content that's not valid UTF-8."""

    def test_binary_content_with_replace(self):
        """Binary content decoded with errors='replace' should not crash."""
        binary = bytes(range(256))
        result = process_file(binary, "data.txt")
        assert result.content_type == "text"
        # Non-UTF8 bytes are replaced with replacement character
        assert "\ufffd" in result.text

    def test_mixed_utf8_and_binary(self):
        """Mix of valid UTF-8 and invalid bytes."""
        content = "Hello ".encode("utf-8") + b"\xff\xfe" + " World".encode("utf-8")
        result = process_file(content, "mixed.log")
        assert result.content_type == "text"
        assert "Hello" in result.text
        assert "World" in result.text


class TestProcessFileParamForwarding:
    """Test that process_file forwards parameters correctly."""

    def test_max_image_dimension_forwarded(self):
        """max_image_dimension should be passed to process_image."""
        png = _make_large_png(2048, 2048)
        result = process_file(png, "big.png", max_image_dimension=256)
        assert "resized_to" in result.metadata
        resized = result.metadata["resized_to"]
        w, h = map(int, resized.split("x"))
        assert w <= 256
        assert h <= 256

    def test_max_pdf_pages_forwarded(self):
        """max_pdf_pages should be passed to process_pdf."""
        pdf = _make_pdf(pages=5)
        result = process_file(pdf, "doc.pdf", max_pdf_pages=2)
        assert "3 more pages not extracted" in result.text


class TestProcessFileSpecialFilenames:
    """Test with special characters and unusual filenames."""

    def test_filename_with_spaces(self):
        result = process_file(b"data", "my file name.txt")
        assert result.content_type == "text"

    def test_filename_with_unicode(self):
        result = process_file(b"data", "report_2025_final.txt")
        assert result.content_type == "text"

    def test_filename_with_chinese(self):
        result = process_file(b"data", "report_final.txt")
        assert result.content_type == "text"

    def test_filename_no_extension(self):
        """File with no extension should be unsupported."""
        result = process_file(b"data", "noextfile")
        assert result.content_type == "unsupported"

    def test_filename_multiple_dots(self):
        """File like 'photo.backup.png' should use last extension."""
        png = _make_png()
        result = process_file(png, "photo.backup.png")
        assert result.content_type == "image"

    def test_filename_multiple_dots_text(self):
        result = process_file(b"data", "report.v2.final.txt")
        assert result.content_type == "text"

    def test_filename_dot_only(self):
        """Filename that is just a dot."""
        result = process_file(b"data", ".")
        # '.' has no extension after rsplit
        assert result.content_type == "unsupported"

    def test_filename_leading_dot(self):
        """Dotfile like '.gitignore' — no recognized extension."""
        result = process_file(b"data", ".gitignore")
        # rsplit('.', 1) -> ['', 'gitignore'], ext = 'gitignore' which is unsupported
        assert result.content_type == "unsupported"


# ════════════════════════════════════════════════════════
# 4. detect_type() Additional Cases
# ════════════════════════════════════════════════════════


class TestDetectTypeUppercase:
    """Test detect_type with uppercase and mixed-case extensions."""

    def test_uppercase_png(self):
        assert detect_type("photo.PNG") == "image"

    def test_uppercase_jpg(self):
        assert detect_type("photo.JPG") == "image"

    def test_uppercase_jpeg(self):
        assert detect_type("photo.JPEG") == "image"

    def test_uppercase_gif(self):
        assert detect_type("anim.GIF") == "image"

    def test_uppercase_bmp(self):
        assert detect_type("img.BMP") == "image"

    def test_uppercase_webp(self):
        assert detect_type("img.WEBP") == "image"

    def test_uppercase_pdf(self):
        assert detect_type("doc.PDF") == "pdf"

    def test_uppercase_txt(self):
        assert detect_type("file.TXT") == "text"

    def test_uppercase_py(self):
        assert detect_type("script.PY") == "text"

    def test_uppercase_json(self):
        assert detect_type("data.JSON") == "text"


class TestDetectTypeMixedCase:
    """Test detect_type with mixed-case extensions."""

    def test_mixed_png(self):
        assert detect_type("photo.Png") == "image"

    def test_mixed_jpeg(self):
        assert detect_type("photo.jPeG") == "image"

    def test_mixed_pdf(self):
        assert detect_type("doc.Pdf") == "pdf"

    def test_mixed_csv(self):
        assert detect_type("data.CsV") == "text"

    def test_mixed_html(self):
        assert detect_type("page.HtMl") == "text"


class TestDetectTypeAllImageFormats:
    """Test detect_type recognizes all supported image extensions."""

    @pytest.mark.parametrize("ext", sorted(IMAGE_EXTENSIONS))
    def test_image_extension(self, ext):
        assert detect_type(f"file.{ext}") == "image"


class TestDetectTypeAllTextFormats:
    """Test detect_type recognizes all supported text extensions."""

    @pytest.mark.parametrize("ext", sorted(TEXT_EXTENSIONS))
    def test_text_extension(self, ext):
        assert detect_type(f"file.{ext}") == "text"


class TestDetectTypeAllPdfFormats:
    """Test detect_type recognizes PDF extension."""

    @pytest.mark.parametrize("ext", sorted(PDF_EXTENSIONS))
    def test_pdf_extension(self, ext):
        assert detect_type(f"file.{ext}") == "pdf"


class TestDetectTypeDocFormats:
    """Test detect_type for doc/docx treated as text."""

    def test_docx(self):
        assert detect_type("report.docx") == "text"

    def test_doc(self):
        assert detect_type("report.doc") == "text"


class TestDetectTypeEdgeCases:
    """Edge cases for detect_type."""

    def test_no_extension(self):
        assert detect_type("README") == "unsupported"

    def test_empty_string(self):
        assert detect_type("") == "unsupported"

    def test_only_extension(self):
        """Filename like '.png'."""
        # rsplit('.', 1) -> ['', 'png'], ext = 'png'
        assert detect_type(".png") == "image"

    def test_double_extension_uses_last(self):
        assert detect_type("archive.tar.gz") == "unsupported"  # gz not supported

    def test_double_extension_text(self):
        assert detect_type("data.backup.json") == "text"  # json is supported

    def test_path_like_filename(self):
        """Filename containing path separators."""
        # rsplit('.', 1) on "some/path/file.txt" gives ext = "txt"
        assert detect_type("some/path/file.txt") == "text"

    def test_unsupported_formats(self):
        for ext in ("zip", "rar", "exe", "bin", "dll", "so", "tar", "gz", "7z"):
            assert detect_type(f"file.{ext}") == "unsupported", f".{ext} should be unsupported"


# ════════════════════════════════════════════════════════
# ProcessedContent dataclass tests
# ════════════════════════════════════════════════════════


class TestProcessedContent:
    """Test the ProcessedContent dataclass itself."""

    def test_default_values(self):
        pc = ProcessedContent(content_type="text")
        assert pc.text is None
        assert pc.image_base64 is None
        assert pc.image_media_type is None
        assert pc.metadata is None
        assert pc.error is None

    def test_all_fields(self):
        pc = ProcessedContent(
            content_type="image",
            text="fallback text",
            image_base64="abc123",
            image_media_type="image/png",
            metadata={"width": 100},
            error=None,
        )
        assert pc.content_type == "image"
        assert pc.image_base64 == "abc123"
        assert pc.metadata["width"] == 100
