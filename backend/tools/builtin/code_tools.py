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
import os
import time

from core.context import current_event_bus, current_sandbox, current_tenant_id, current_user_id, current_session_id
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
    sandbox = current_sandbox.get(None)
    if sandbox is None:
        return None, None
    tenant_id = current_tenant_id.get("default")
    user_id = current_user_id.get("anonymous")
    session_id = current_session_id.get("")
    workspace = sandbox.get_workspace(tenant_id, user_id, session_id)
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
        "超过 50KB 的内容会被截断。"
    ),
    read_only=True,
)
def read_source_file(
    path: str,          # 文件路径
    start_line: int = 0,  # 起始行号 (1-based, 0=全文)
    end_line: int = 0,    # 结束行号 (1-based, 0=全文)
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


@code_capability_registry.tool(
    description=(
        "写入/创建源代码文件。"
        "mode: create(仅创建新文件) | overwrite(覆盖已有文件) | patch(追加到文件末尾)。"
        "overwrite 模式会在写入前创建 .bak 备份。"
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

    # A6: 磁盘配额检查
    sandbox = current_sandbox.get(None)
    if sandbox:
        tenant_id = current_tenant_id.get("default")
        user_id = current_user_id.get("anonymous")
        quota = sandbox.check_disk_quota(tenant_id, user_id)
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

        # 发射 SSE 事件
        bus = current_event_bus.get()
        if bus:
            bus.emit("code_file_written", {
                "path": path,
                "mode": mode,
                "size": size,
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
        bus = current_event_bus.get()
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
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
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

        bus = current_event_bus.get()
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
