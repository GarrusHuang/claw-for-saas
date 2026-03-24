"""
编码能力工具。

Agent 可读写源代码文件、执行 Shell 命令。
安全性由 A6 SandboxManager 保障:
- 文件操作限制在 workspace 内 (SandboxManager.validate_path)
- 命令执行通过沙箱 (本地 subprocess 或 Docker 容器)
- 磁盘配额检查 (写入前)
- 命令黑名单快速拒绝
- 回退: 无 sandbox 时使用 CODE_ALLOWED_PATHS 环境变量
"""

from __future__ import annotations

import asyncio
import logging
import mimetypes
import os
import time

from core.context import get_request_context
from core.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)

code_capability_registry = ToolRegistry()

# 最大文件读取大小 (50KB)
MAX_READ_SIZE = 50 * 1024
# 最大命令输出大小 (10KB)
MAX_OUTPUT_SIZE = 10 * 1024


def _get_workspace() -> tuple:
    """
    获取当前 workspace 和 SandboxManager。

    Returns:
        (sandbox, workspace) 或 (None, None)
    """
    ctx = get_request_context()
    sandbox = ctx.sandbox
    if sandbox is None:
        return None, None
    workspace = sandbox.get_workspace(ctx.tenant_id, ctx.user_id, ctx.session_id)
    return sandbox, workspace


def _resolve_safe_path(path: str) -> str:
    """
    解析并验证路径安全性。

    优先使用 SandboxManager (A6)，回退到 CODE_ALLOWED_PATHS 环境变量。
    """
    sandbox, workspace = _get_workspace()

    # A6: 使用 SandboxManager 验证
    if sandbox and workspace:
        # 如果 path 是相对路径，基于 workspace 解析
        if not os.path.isabs(path):
            path = os.path.join(workspace, path)
        return sandbox.validate_path(path, workspace)

    # 回退: CODE_ALLOWED_PATHS (兼容无 sandbox 的场景)
    resolved = os.path.realpath(os.path.expanduser(path))

    allowed_raw = os.environ.get("CODE_ALLOWED_PATHS", "")
    if allowed_raw:
        allowed_dirs = [os.path.realpath(p.strip()) for p in allowed_raw.split(",") if p.strip()]
    else:
        allowed_dirs = [os.path.realpath(os.getcwd())]

    for allowed in allowed_dirs:
        if resolved.startswith(allowed + os.sep) or resolved == allowed:
            return resolved

    raise PermissionError(
        f"路径 {path} 不在允许目录中。"
        f"允许的目录: {', '.join(allowed_dirs)}"
    )


@code_capability_registry.tool(
    description=(
        "读取源代码文件内容。"
        "传入文件路径，可选 start_line/end_line 指定行范围 (0 表示读全文)。"
        "indent_block='class Foo' 可按缩进读取代码块 (如类/函数定义)。"
        "超过 50KB 的内容会被截断。"
    ),
    read_only=True,
)
def read_source_file(
    path: str,          # 文件路径
    start_line: int = 0,  # 起始行号 (1-based, 0=全文)
    end_line: int = 0,    # 结束行号 (1-based, 0=全文)
    indent_block: str = "",  # 按缩进读取代码块 (匹配首行后读取同级及更深缩进的行)
) -> dict:
    """读取指定路径的源代码文件内容。"""
    try:
        resolved = _resolve_safe_path(path)
    except PermissionError as e:
        return {"error": str(e)}

    if not os.path.isfile(resolved):
        return {"error": f"文件不存在: {path}"}

    try:
        file_size = os.path.getsize(resolved)
        with open(resolved, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        lines = content.split("\n")
        total_lines = len(lines)

        # 缩进模式: 找到匹配行，读取该块及其缩进内的所有子行
        if indent_block:
            block_lines, block_start = _extract_indent_block(lines, indent_block)
            if block_lines is not None:
                content = "\n".join(block_lines)
                return {
                    "path": path,
                    "content": content,
                    "line_count": total_lines,
                    "block_start_line": block_start + 1,
                    "block_line_count": len(block_lines),
                    "size_bytes": file_size,
                    "truncated": False,
                }
            return {"error": f"未找到匹配的代码块: {indent_block}"}

        # 行范围过滤
        if start_line > 0 or end_line > 0:
            sl = max(1, start_line) - 1  # 转 0-based
            el = end_line if end_line > 0 else total_lines
            lines = lines[sl:el]
            content = "\n".join(lines)

        # 截断过长内容
        truncated = False
        if len(content.encode("utf-8")) > MAX_READ_SIZE:
            content = content[:MAX_READ_SIZE]
            truncated = True

        return {
            "path": path,
            "content": content,
            "line_count": total_lines,
            "size_bytes": file_size,
            "truncated": truncated,
        }

    except Exception as e:
        logger.error(f"read_source_file error: {e}")
        return {"error": str(e)}


def _extract_indent_block(
    lines: list[str], pattern: str,
) -> tuple[list[str] | None, int]:
    """
    按缩进读取代码块: 匹配首行后，读取同级及更深缩进的所有后续行。

    Returns:
        (block_lines, start_index) 或 (None, -1) 如果未找到。
    """
    # 找到匹配行
    start_idx = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        if pattern in stripped:
            start_idx = i
            break

    if start_idx < 0:
        return None, -1

    # 确定基准缩进
    base_line = lines[start_idx]
    base_indent = len(base_line) - len(base_line.lstrip())

    # 收集块: 首行 + 后续缩进更深的行 (遇到同级或更浅的非空行停止)
    block = [base_line]
    for i in range(start_idx + 1, len(lines)):
        line = lines[i]
        if not line.strip():
            block.append(line)  # 保留空行
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= base_indent:
            break
        block.append(line)

    # 去掉尾部空行
    while block and not block[-1].strip():
        block.pop()

    return block, start_idx


@code_capability_registry.tool(
    description=(
        "写入/创建源代码文件。"
        "mode: create(仅创建新文件) | overwrite(覆盖已有文件) | patch(追加到文件末尾)。"
        "overwrite 模式会在写入前创建 .bak 备份。"
        "【大文件分段写入 — 强制规则】内容超过 3000 字符时，禁止压缩/简化内容，必须分段写入: "
        "第一段 mode=create (≤3000字符), 后续段 mode=patch 追加 (≤3000字符/段)。"
        "保持完整内容，不要为了缩短而删减。"
    ),
    read_only=False,
)
def write_source_file(
    path: str,           # 文件路径
    content: str,        # 文件内容
    mode: str = "overwrite",  # create | overwrite | patch
) -> dict:
    """写入/创建源代码文件。"""
    try:
        resolved = _resolve_safe_path(path)
    except PermissionError as e:
        return {"error": str(e)}

    # TurnDiffTracker: 捕获写入前基线
    ctx = get_request_context()
    if ctx.diff_tracker:
        ctx.diff_tracker.capture_baseline(resolved)

    # A6: 磁盘配额检查
    if ctx.sandbox:
        quota = ctx.sandbox.check_disk_quota(ctx.tenant_id, ctx.user_id)
        if quota["exceeded"]:
            return {"error": f"磁盘配额超限: 已使用 {quota['used_mb']}MB / {quota['quota_mb']}MB"}

    backup_path = None

    try:
        if mode == "create":
            if os.path.exists(resolved):
                return {"error": f"文件已存在: {path} — create 模式不可覆盖"}
            # 创建目录 (如需)
            os.makedirs(os.path.dirname(resolved), exist_ok=True)
            with open(resolved, "w", encoding="utf-8") as f:
                f.write(content)

        elif mode == "overwrite":
            # 覆盖前备份
            if os.path.exists(resolved):
                backup_path = resolved + ".bak"
                with open(resolved, "rb") as src:
                    with open(backup_path, "wb") as dst:
                        dst.write(src.read())
            else:
                os.makedirs(os.path.dirname(resolved), exist_ok=True)
            with open(resolved, "w", encoding="utf-8") as f:
                f.write(content)

        elif mode == "patch":
            if not os.path.exists(resolved):
                return {"error": f"文件不存在: {path} — patch 模式需要已有文件"}
            with open(resolved, "a", encoding="utf-8") as f:
                f.write(content)

        else:
            return {"error": f"无效 mode: {mode} — 支持: create, overwrite, patch"}

        size = os.path.getsize(resolved)
        basename = os.path.basename(resolved)
        mime_type = mimetypes.guess_type(basename)[0] or "application/octet-stream"

        # TurnDiffTracker: 记录写入操作
        if ctx.diff_tracker:
            ctx.diff_tracker.record_write(resolved, "create" if mode == "create" else "modify")

        # 发射 SSE 事件
        bus = ctx.event_bus
        if bus:
            bus.emit("code_file_written", {
                "path": path,
                "mode": mode,
                "size": size,
            })
            bus.emit("file_artifact", {
                "path": path,
                "filename": basename,
                "size_bytes": size,
                "content_type": mime_type,
                "session_id": ctx.session_id,
            })

        result = {"path": path, "mode": mode, "size": size}
        if backup_path:
            result["backup_path"] = backup_path
        return result

    except Exception as e:
        logger.error(f"write_source_file error: {e}")
        return {"error": str(e)}


@code_capability_registry.tool(
    description=(
        "撤销本轮对话中所有文件修改，恢复到修改前的状态。"
        "基于 TurnDiffTracker 的 baseline 快照恢复。"
        "仅在本轮有文件修改时有效。"
    ),
    read_only=False,
)
def undo_file_changes() -> dict:
    """#20 Undo: 恢复本轮修改的所有文件到 baseline 状态。"""
    ctx = get_request_context()
    if not ctx.diff_tracker:
        return {"error": "当前会话没有文件变更追踪器"}
    results = ctx.diff_tracker.undo_all()
    if not results:
        return {"message": "本轮没有文件修改需要撤销"}
    return {
        "undone": len(results),
        "details": results,
    }


@code_capability_registry.tool(
    description=(
        "在沙箱中执行 Shell 命令。"
        "timeout 指定超时秒数 (默认 30, 最大 120)。"
        "输出超过 10KB 会被截断。"
    ),
    read_only=False,
)
def run_command(
    command: str,        # Shell 命令
    cwd: str = "",       # 工作目录 (可选)
    timeout: int = 30,   # 超时秒数
) -> dict:
    """在沙箱中执行 Shell 命令。"""
    import subprocess

    # #11: 执行前检查 CancellationToken
    try:
        ctx = get_request_context()
        if ctx.cancellation_token and ctx.cancellation_token.is_cancelled:
            return {"error": "命令执行已被取消", "cancelled": True}
    except Exception:
        pass

    sandbox, workspace = _get_workspace()

    # A6: 优先使用 SandboxManager 执行 (Docker 或本地沙箱)
    if sandbox and workspace:
        # cwd 必须在 workspace 内
        work_dir = workspace
        if cwd:
            try:
                work_dir = sandbox.validate_path(
                    cwd if os.path.isabs(cwd) else os.path.join(workspace, cwd),
                    workspace,
                )
            except PermissionError as e:
                return {"error": str(e)}
            if not os.path.isdir(work_dir):
                return {"error": f"工作目录不存在: {cwd}"}

        result = sandbox.run_command(command, work_dir, timeout)

        # 发射 SSE 事件
        bus = get_request_context().event_bus
        if bus:
            bus.emit("command_executed", {
                "command": command[:200],
                "exit_code": result.get("exit_code", -1),
                "duration_ms": result.get("duration_ms", 0),
                "sandbox": result.get("sandbox", "unknown"),
            })

        return result

    # 回退: 直接 subprocess (兼容无 sandbox 场景)
    timeout = min(max(1, timeout), 120)

    work_dir = None
    if cwd:
        try:
            work_dir = _resolve_safe_path(cwd)
            if not os.path.isdir(work_dir):
                return {"error": f"工作目录不存在: {cwd}"}
        except PermissionError as e:
            return {"error": str(e)}

    start = time.monotonic()

    try:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=work_dir,
            env={k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG", "PYTHONIOENCODING", "TERM")},
        )

        duration_ms = round((time.monotonic() - start) * 1000, 1)

        stdout = proc.stdout or ""
        stderr = proc.stderr or ""

        stdout_truncated = False
        stderr_truncated = False
        if len(stdout.encode("utf-8")) > MAX_OUTPUT_SIZE:
            stdout = stdout[:MAX_OUTPUT_SIZE]
            stdout_truncated = True
        if len(stderr.encode("utf-8")) > MAX_OUTPUT_SIZE:
            stderr = stderr[:MAX_OUTPUT_SIZE]
            stderr_truncated = True

        bus = get_request_context().event_bus
        if bus:
            bus.emit("command_executed", {
                "command": command[:200],
                "exit_code": proc.returncode,
                "duration_ms": duration_ms,
            })

        return {
            "exit_code": proc.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "duration_ms": duration_ms,
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
        }

    except subprocess.TimeoutExpired:
        duration_ms = round((time.monotonic() - start) * 1000, 1)
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": f"命令超时 (>{timeout}s)",
            "duration_ms": duration_ms,
            "timed_out": True,
        }
    except Exception as e:
        logger.error(f"run_command error: {e}")
        return {"error": str(e)}
