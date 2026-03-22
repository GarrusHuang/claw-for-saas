"""
工作空间搜索工具 — grep_files / list_dir。

比 run_command('grep/ls') 更安全:
- 纯 Python 实现，不调用 shell
- 路径验证通过 SandboxManager.validate_path
- 跳过二进制文件
- 结果大小限制
"""

from __future__ import annotations

import fnmatch
import logging
import os
import re
import time

from core.context import get_request_context
from core.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)

search_tools_registry = ToolRegistry()

# 二进制检测: 前 8KB 含 null 字节
_BINARY_CHECK_SIZE = 8192
# 最大遍历文件数 (防止巨大目录卡住)
_MAX_FILES_WALK = 50000


def _get_workspace() -> tuple:
    """获取当前 workspace 和 SandboxManager。"""
    ctx = get_request_context()
    sandbox = ctx.sandbox
    if sandbox is None:
        return None, None
    workspace = sandbox.get_workspace(ctx.tenant_id, ctx.user_id, ctx.session_id)
    return sandbox, workspace


def _resolve_safe_path(path: str) -> str:
    """解析并验证路径在 workspace 内。"""
    sandbox, workspace = _get_workspace()
    if sandbox and workspace:
        if not os.path.isabs(path):
            path = os.path.join(workspace, path)
        return sandbox.validate_path(path, workspace)

    # 回退: 当前工作目录
    resolved = os.path.realpath(os.path.expanduser(path))
    cwd = os.path.realpath(os.getcwd())
    if resolved == cwd or resolved.startswith(cwd + os.sep):
        return resolved
    raise PermissionError(f"路径 {path} 不在工作空间内")


def _is_binary(filepath: str) -> bool:
    """检测文件是否为二进制 (前 8KB 含 null 字节)。"""
    try:
        with open(filepath, "rb") as f:
            chunk = f.read(_BINARY_CHECK_SIZE)
        return b"\x00" in chunk
    except (OSError, IOError):
        return True


@search_tools_registry.tool(
    description="在工作空间中搜索文件内容 (正则)。比 run_command('grep') 更安全。",
    read_only=True,
)
def grep_files(
    pattern: str,
    path: str = ".",
    include: str = "",
    max_results: int = 100,
    context_lines: int = 0,
) -> dict:
    """
    搜索文件内容。

    Args:
        pattern: Python 正则表达式
        path: 搜索起始路径 (相对于工作空间)
        include: glob 过滤 (如 "*.py")
        max_results: 最大匹配数
        context_lines: 上下文行数
    """
    try:
        search_root = _resolve_safe_path(path)
    except PermissionError as e:
        return {"error": str(e)}

    if not os.path.exists(search_root):
        return {"error": f"路径不存在: {path}"}

    try:
        regex = re.compile(pattern)
    except re.error as e:
        return {"error": f"无效正则表达式: {e}"}

    max_results = min(max(1, max_results), 1000)
    context_lines = min(max(0, context_lines), 10)

    matches = []
    files_searched = 0
    truncated = False

    if os.path.isfile(search_root):
        file_list = [search_root]
    else:
        file_list = []
        for dirpath, _, filenames in os.walk(search_root):
            for fname in filenames:
                if include and not fnmatch.fnmatch(fname, include):
                    continue
                file_list.append(os.path.join(dirpath, fname))
                if len(file_list) >= _MAX_FILES_WALK:
                    break
            if len(file_list) >= _MAX_FILES_WALK:
                break

    for filepath in file_list:
        if _is_binary(filepath):
            continue
        files_searched += 1

        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except (OSError, IOError):
            continue

        for i, line in enumerate(lines):
            if regex.search(line):
                rel_path = os.path.relpath(filepath, search_root) if os.path.isdir(search_root) else os.path.basename(filepath)
                match_entry = {
                    "file": rel_path,
                    "line_number": i + 1,
                    "text": line.rstrip("\n\r"),
                }

                if context_lines > 0:
                    start = max(0, i - context_lines)
                    end = min(len(lines), i + context_lines + 1)
                    ctx_lines = [l.rstrip("\n\r") for l in lines[start:end]]
                    match_entry["context"] = ctx_lines

                matches.append(match_entry)
                if len(matches) >= max_results:
                    truncated = True
                    break

        if truncated:
            break

    return {
        "matches": matches,
        "match_count": len(matches),
        "files_searched": files_searched,
        "truncated": truncated,
    }


@search_tools_registry.tool(
    description="列出工作空间目录结构，含文件类型、大小、修改时间。",
    read_only=True,
)
def list_dir(
    path: str = ".",
    depth: int = 2,
    include: str = "",
    offset: int = 0,
    limit: int = 200,
) -> dict:
    """
    列出目录结构。

    Args:
        path: 目录路径 (相对于工作空间)
        depth: 遍历深度 (max 10)
        include: glob 过滤 (如 "*.py")
        offset: 分页偏移
        limit: 分页大小
    """
    try:
        target = _resolve_safe_path(path)
    except PermissionError as e:
        return {"error": str(e)}

    if not os.path.exists(target):
        return {"error": f"路径不存在: {path}"}
    if not os.path.isdir(target):
        return {"error": f"不是目录: {path}"}

    depth = min(max(1, depth), 10)
    limit = min(max(1, limit), 1000)
    offset = max(0, offset)

    entries = []

    def _walk(dir_path: str, current_depth: int):
        if current_depth > depth:
            return
        try:
            items = sorted(os.listdir(dir_path))
        except OSError:
            return

        # 目录优先排序
        dirs = []
        files = []
        for item in items:
            full = os.path.join(dir_path, item)
            if os.path.isdir(full):
                dirs.append(item)
            else:
                files.append(item)

        for name in dirs:
            full = os.path.join(dir_path, name)
            rel = os.path.relpath(full, target)
            entries.append({
                "path": rel,
                "type": "directory",
                "size": 0,
                "mtime": os.path.getmtime(full),
            })
            _walk(full, current_depth + 1)

        for name in files:
            if include and not fnmatch.fnmatch(name, include):
                continue
            full = os.path.join(dir_path, name)
            try:
                stat = os.stat(full)
                entries.append({
                    "path": os.path.relpath(full, target),
                    "type": "file",
                    "size": stat.st_size,
                    "mtime": stat.st_mtime,
                })
            except OSError:
                continue

    _walk(target, 1)

    total = len(entries)
    paged = entries[offset:offset + limit]
    has_more = (offset + limit) < total

    return {
        "entries": paged,
        "total": total,
        "has_more": has_more,
    }
