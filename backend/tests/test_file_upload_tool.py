"""
T4: 文件上传 → 工具读取端到端测试。

验证通过 FileService 上传文件后，read_uploaded_file 工具能正确读取内容。
"""
from __future__ import annotations

import io
import os
import tempfile

import pytest

from services.file_service import FileService
from core.context import current_file_service, current_tenant_id, current_user_id, current_session_id


@pytest.fixture
def file_service(tmp_path):
    """创建临时 FileService。"""
    return FileService(base_dir=str(tmp_path / "files"))


class TestFileUploadToToolRead:
    """完整链路: 上传文件 → 通过工具读取。"""

    def test_upload_and_read_txt(self, file_service):
        """上传 TXT 文件后通过 read_uploaded_file 读取。"""
        content = "这是测试文件的内容。\n第二行内容。"

        # 上传文件
        meta = file_service.save_file(
            tenant_id="T1",
            user_id="U1",
            filename="test.txt",
            content=content.encode("utf-8"),
        )
        file_id = meta.file_id

        # 设置 contextvars
        current_file_service.set(file_service)
        current_tenant_id.set("T1")
        current_user_id.set("U1")
        current_session_id.set("sess-test")

        # 调用工具
        from tools.builtin.file_tools import read_uploaded_file
        tool_result = read_uploaded_file(file_id=file_id)

        assert "error" not in tool_result
        assert tool_result.get("filename") == "test.txt"
        text = tool_result.get("text", "")
        assert "测试文件" in text

    def test_upload_and_read_json(self, file_service):
        """上传 JSON 文件后读取。"""
        data = '{"name": "张三", "age": 30}'
        meta = file_service.save_file(
            tenant_id="T1",
            user_id="U1",
            filename="data.json",
            content=data.encode("utf-8"),
        )
        file_id = meta.file_id

        current_file_service.set(file_service)
        current_tenant_id.set("T1")
        current_user_id.set("U1")
        current_session_id.set("sess-test")

        from tools.builtin.file_tools import read_uploaded_file
        tool_result = read_uploaded_file(file_id=file_id)

        assert "error" not in tool_result
        text = tool_result.get("text", "")
        assert "张三" in text

    def test_read_nonexistent_file(self, file_service):
        """读取不存在的文件应返回错误。"""
        current_file_service.set(file_service)
        current_tenant_id.set("T1")
        current_user_id.set("U1")
        current_session_id.set("sess-test")

        from tools.builtin.file_tools import read_uploaded_file
        tool_result = read_uploaded_file(file_id="nonexistent-id")

        assert "error" in tool_result or "not found" in str(tool_result).lower() or not tool_result.get("text")
