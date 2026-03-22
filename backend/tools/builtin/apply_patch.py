"""
apply_patch — 增量文件编辑工具。

使用 search/replace 格式的 patch (与 Codex 相同格式)，
支持 Add / Delete / Update 三种操作，大幅减少 token 消耗。

Patch 格式:
    *** Begin Patch
    *** Add File: <path>
    +line1
    +line2
    *** Update File: <path>
    @@ context_hint
     context_line
    -old_line
    +new_line
    *** Delete File: <path>
    *** End Patch
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

from core.context import get_request_context
from core.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)

apply_patch_registry = ToolRegistry()


# ── Patch 数据结构 ──


@dataclass
class UpdateChunk:
    """一个 @@ 块: context + old/new lines。"""
    context_hint: str | None = None
    old_lines: list[str] = field(default_factory=list)
    new_lines: list[str] = field(default_factory=list)
    is_eof: bool = False


@dataclass
class AddFile:
    path: str
    contents: str


@dataclass
class DeleteFile:
    path: str


@dataclass
class UpdateFile:
    path: str
    move_to: str | None = None
    chunks: list[UpdateChunk] = field(default_factory=list)


Hunk = AddFile | DeleteFile | UpdateFile


# ── 解析器 ──


class PatchParseError(Exception):
    pass


def parse_patch(text: str) -> list[Hunk]:
    """解析 patch 文本，返回操作列表。"""
    lines = text.strip().splitlines()
    if not lines:
        raise PatchParseError("Empty patch")

    # 找到 Begin/End markers
    first = lines[0].strip()
    last = lines[-1].strip()
    if first != "*** Begin Patch":
        raise PatchParseError("Patch must start with '*** Begin Patch'")
    if last != "*** End Patch":
        raise PatchParseError("Patch must end with '*** End Patch'")

    hunks: list[Hunk] = []
    body = lines[1:-1]  # 去掉 Begin/End
    i = 0

    while i < len(body):
        line = body[i].strip()

        if line.startswith("*** Add File: "):
            path = line[len("*** Add File: "):]
            contents_lines: list[str] = []
            i += 1
            while i < len(body):
                if body[i].startswith("+"):
                    contents_lines.append(body[i][1:])
                    i += 1
                else:
                    break
            contents = "\n".join(contents_lines) + "\n" if contents_lines else ""
            hunks.append(AddFile(path=path, contents=contents))

        elif line.startswith("*** Delete File: "):
            path = line[len("*** Delete File: "):]
            hunks.append(DeleteFile(path=path))
            i += 1

        elif line.startswith("*** Update File: "):
            path = line[len("*** Update File: "):]
            i += 1

            # Optional: *** Move to:
            move_to = None
            if i < len(body) and body[i].strip().startswith("*** Move to: "):
                move_to = body[i].strip()[len("*** Move to: "):]
                i += 1

            chunks: list[UpdateChunk] = []
            first_chunk = True

            while i < len(body):
                stripped = body[i].strip()
                # 下一个 file 操作
                if stripped.startswith("***") and not stripped == "*** End of File":
                    break
                # 空行跳过
                if not stripped:
                    i += 1
                    continue

                # 解析一个 chunk
                chunk, consumed = _parse_chunk(body, i, first_chunk)
                chunks.append(chunk)
                i += consumed
                first_chunk = False

            if not chunks:
                raise PatchParseError(f"Update hunk for '{path}' has no chunks")
            hunks.append(UpdateFile(path=path, move_to=move_to, chunks=chunks))

        else:
            raise PatchParseError(f"Unexpected line: '{line}'")

    return hunks


def _parse_chunk(lines: list[str], start: int, allow_no_context: bool) -> tuple[UpdateChunk, int]:
    """解析一个 @@ chunk，返回 (chunk, consumed_lines)。"""
    i = start
    context_hint = None

    # 检查 @@ marker
    stripped = lines[i].strip()
    if stripped == "@@":
        context_hint = None
        i += 1
    elif stripped.startswith("@@ "):
        context_hint = stripped[3:]
        i += 1
    elif not allow_no_context:
        raise PatchParseError(f"Expected @@ marker, got: '{stripped}'")

    chunk = UpdateChunk(context_hint=context_hint)
    has_lines = False

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # End of File marker
        if stripped == "*** End of File":
            chunk.is_eof = True
            i += 1
            break

        # 下一个 @@ 块或 *** 操作
        if stripped.startswith("@@") or (stripped.startswith("***") and stripped != "*** End of File"):
            break

        # diff 行
        if not line:
            # 空行作为 context
            chunk.old_lines.append("")
            chunk.new_lines.append("")
            has_lines = True
            i += 1
        elif line[0] == " ":
            chunk.old_lines.append(line[1:])
            chunk.new_lines.append(line[1:])
            has_lines = True
            i += 1
        elif line[0] == "-":
            chunk.old_lines.append(line[1:])
            has_lines = True
            i += 1
        elif line[0] == "+":
            chunk.new_lines.append(line[1:])
            has_lines = True
            i += 1
        else:
            if not has_lines:
                raise PatchParseError(
                    f"Unexpected line in chunk: '{line}'. "
                    "Lines must start with ' ' (context), '+' (add), or '-' (remove)"
                )
            break

    if not has_lines:
        raise PatchParseError("Empty chunk — no diff lines found")

    return chunk, i - start


# ── 序列匹配 (fuzzy) ──


def _seek_sequence(
    lines: list[str], pattern: list[str], start: int, eof: bool,
) -> int | None:
    """
    在 lines 中从 start 位置开始查找 pattern 序列。

    匹配优先级: 精确 → trim trailing → trim both sides。
    eof=True 时优先从文件末尾开始搜索。
    """
    if not pattern:
        return start
    if len(pattern) > len(lines):
        return None

    search_start = (len(lines) - len(pattern)) if eof and len(lines) >= len(pattern) else start

    # Pass 1: 精确匹配
    for i in range(search_start, len(lines) - len(pattern) + 1):
        if lines[i:i + len(pattern)] == pattern:
            return i

    # Pass 2: trim trailing whitespace
    for i in range(search_start, len(lines) - len(pattern) + 1):
        if all(
            lines[i + j].rstrip() == pattern[j].rstrip()
            for j in range(len(pattern))
        ):
            return i

    # Pass 3: trim both sides
    for i in range(search_start, len(lines) - len(pattern) + 1):
        if all(
            lines[i + j].strip() == pattern[j].strip()
            for j in range(len(pattern))
        ):
            return i

    # 如果 eof 模式先搜文件末尾没找到，回退到从 start 搜索
    if eof and search_start > start:
        for i in range(start, search_start):
            if all(
                lines[i + j].strip() == pattern[j].strip()
                for j in range(len(pattern))
            ):
                return i

    return None


# ── 应用逻辑 ──


class PatchApplyError(Exception):
    pass


def _apply_update(path: str, chunks: list[UpdateChunk]) -> str:
    """对文件内容应用 update chunks，返回新内容。"""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        original = f.read()

    original_lines = original.split("\n")
    # 去掉末尾空行 (与 split("\n") 的 trailing empty 一致)
    if original_lines and original_lines[-1] == "":
        original_lines.pop()

    replacements: list[tuple[int, int, list[str]]] = []
    line_idx = 0

    for chunk in chunks:
        # context_hint 定位
        if chunk.context_hint is not None:
            found = _seek_sequence(
                original_lines, [chunk.context_hint], line_idx, eof=False,
            )
            if found is not None:
                line_idx = found + 1
            else:
                raise PatchApplyError(
                    f"Context '{chunk.context_hint}' not found in {path}"
                )

        if not chunk.old_lines:
            # 纯插入 — 插入到文件末尾 (或最后一个非空行之前)
            insertion_idx = len(original_lines)
            replacements.append((insertion_idx, 0, chunk.new_lines[:]))
            continue

        # 查找 old_lines
        pattern = chunk.old_lines[:]
        found = _seek_sequence(original_lines, pattern, line_idx, chunk.is_eof)

        # 兜底: 如果末尾是空行导致匹配不上，去掉末尾空行重试
        new_slice = chunk.new_lines[:]
        if found is None and pattern and pattern[-1] == "":
            pattern = pattern[:-1]
            if new_slice and new_slice[-1] == "":
                new_slice = new_slice[:-1]
            found = _seek_sequence(original_lines, pattern, line_idx, chunk.is_eof)

        if found is None:
            preview = "\n".join(chunk.old_lines[:5])
            raise PatchApplyError(
                f"Could not find expected lines in {path}:\n{preview}"
            )

        replacements.append((found, len(pattern), new_slice))
        line_idx = found + len(pattern)

    # 按位置排序后逆序应用
    replacements.sort(key=lambda r: r[0])
    result_lines = original_lines[:]
    for start, old_len, new_lines in reversed(replacements):
        del result_lines[start:start + old_len]
        for offset, line in enumerate(new_lines):
            result_lines.insert(start + offset, line)

    # 确保末尾有换行
    if not result_lines or result_lines[-1] != "":
        result_lines.append("")
    return "\n".join(result_lines)


def apply_patch_to_filesystem(
    hunks: list[Hunk], workspace: str,
) -> dict:
    """
    将 patch 应用到文件系统。

    Args:
        hunks: 解析后的操作列表
        workspace: 工作空间根目录 (所有路径相对于此)

    Returns:
        {"added": [...], "modified": [...], "deleted": [...]}
    """
    added: list[str] = []
    modified: list[str] = []
    deleted: list[str] = []

    for hunk in hunks:
        if isinstance(hunk, AddFile):
            full_path = os.path.join(workspace, hunk.path)
            parent = os.path.dirname(full_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(hunk.contents)
            added.append(hunk.path)

        elif isinstance(hunk, DeleteFile):
            full_path = os.path.join(workspace, hunk.path)
            if not os.path.isfile(full_path):
                raise PatchApplyError(f"Cannot delete: file not found: {hunk.path}")
            os.remove(full_path)
            deleted.append(hunk.path)

        elif isinstance(hunk, UpdateFile):
            full_path = os.path.join(workspace, hunk.path)
            if not os.path.isfile(full_path):
                raise PatchApplyError(f"Cannot update: file not found: {hunk.path}")

            new_contents = _apply_update(full_path, hunk.chunks)

            if hunk.move_to:
                dest = os.path.join(workspace, hunk.move_to)
                parent = os.path.dirname(dest)
                if parent:
                    os.makedirs(parent, exist_ok=True)
                with open(dest, "w", encoding="utf-8") as f:
                    f.write(new_contents)
                os.remove(full_path)
                modified.append(hunk.move_to)
            else:
                with open(full_path, "w", encoding="utf-8") as f:
                    f.write(new_contents)
                modified.append(hunk.path)

    return {"added": added, "modified": modified, "deleted": deleted}


# ── 工具注册 ──


def _get_workspace() -> tuple:
    """获取 workspace 和 sandbox。"""
    ctx = get_request_context()
    sandbox = ctx.sandbox
    if sandbox is None:
        return None, None
    workspace = sandbox.get_workspace(ctx.tenant_id, ctx.user_id, ctx.session_id)
    return sandbox, workspace


def _resolve_workspace() -> str:
    """获取工作空间目录，无 sandbox 时使用 CODE_ALLOWED_PATHS。"""
    sandbox, workspace = _get_workspace()
    if workspace:
        return workspace

    allowed_raw = os.environ.get("CODE_ALLOWED_PATHS", "")
    if allowed_raw:
        paths = [p.strip() for p in allowed_raw.split(",") if p.strip()]
        if paths:
            return os.path.realpath(paths[0])
    return os.path.realpath(os.getcwd())


@apply_patch_registry.tool(
    description=(
        "增量编辑文件 — 使用 search/replace patch 格式，只传输变更部分，大幅节省 token。"
        "适用场景: 修改已有文件中的几行代码、多文件批量编辑、创建新文件、删除文件。"
        "patch 参数使用 *** Begin Patch / *** End Patch 包裹。"
        "Update File 的 @@ 块中: 空格开头=上下文行, -开头=删除行, +开头=新增行。"
        "提供 3 行上下文确保匹配唯一。如果上下文不够，用 @@ class_or_function 缩小范围。"
    ),
    read_only=False,
)
def apply_patch(
    patch: str,  # patch 文本 (*** Begin Patch ... *** End Patch)
) -> dict:
    """
    应用增量 patch 到工作空间文件。

    支持三种操作:
    - *** Add File: path — 创建新文件 (内容行以 + 开头)
    - *** Delete File: path — 删除文件
    - *** Update File: path — 增量修改 (search/replace)
    """
    # 磁盘配额检查
    ctx = get_request_context()
    if ctx.sandbox:
        quota = ctx.sandbox.check_disk_quota(ctx.tenant_id, ctx.user_id)
        if quota["exceeded"]:
            return {"error": f"磁盘配额超限: 已使用 {quota['used_mb']}MB / {quota['quota_mb']}MB"}

    # 验证路径安全性
    workspace = _resolve_workspace()

    try:
        hunks = parse_patch(patch)
    except PatchParseError as e:
        return {"error": f"Patch 解析失败: {e}"}

    if not hunks:
        return {"error": "Patch is empty — no operations found"}

    # 验证所有路径在 workspace 内
    for hunk in hunks:
        paths_to_check = []
        if isinstance(hunk, AddFile):
            paths_to_check.append(hunk.path)
        elif isinstance(hunk, DeleteFile):
            paths_to_check.append(hunk.path)
        elif isinstance(hunk, UpdateFile):
            paths_to_check.append(hunk.path)
            if hunk.move_to:
                paths_to_check.append(hunk.move_to)

        for p in paths_to_check:
            if os.path.isabs(p):
                return {"error": f"Absolute paths not allowed: {p}. Use relative paths."}
            full = os.path.realpath(os.path.join(workspace, p))
            if not full.startswith(os.path.realpath(workspace) + os.sep) and full != os.path.realpath(workspace):
                return {"error": f"Path escapes workspace: {p}"}

    # TurnDiffTracker: 捕获所有目标文件的写入前基线
    if ctx.diff_tracker:
        for hunk in hunks:
            if isinstance(hunk, AddFile):
                target = os.path.join(workspace, hunk.path)
                ctx.diff_tracker.capture_baseline(target)
            elif isinstance(hunk, UpdateFile):
                target = os.path.join(workspace, hunk.path)
                ctx.diff_tracker.capture_baseline(target)
            elif isinstance(hunk, DeleteFile):
                target = os.path.join(workspace, hunk.path)
                ctx.diff_tracker.capture_baseline(target)

    try:
        result = apply_patch_to_filesystem(hunks, workspace)
    except (PatchApplyError, OSError) as e:
        return {"error": f"Patch 应用失败: {e}"}

    # TurnDiffTracker: 记录写入操作
    if ctx.diff_tracker:
        for p in result["added"]:
            ctx.diff_tracker.record_write(os.path.join(workspace, p), "create")
        for p in result["modified"]:
            ctx.diff_tracker.record_write(os.path.join(workspace, p), "modify")
        for p in result["deleted"]:
            ctx.diff_tracker.record_write(os.path.join(workspace, p), "delete")

    # 发射事件
    bus = ctx.event_bus
    if bus:
        all_files = result["added"] + result["modified"] + result["deleted"]
        bus.emit("code_patch_applied", {
            "added": result["added"],
            "modified": result["modified"],
            "deleted": result["deleted"],
            "total_files": len(all_files),
        })
        for f in result["added"] + result["modified"]:
            bus.emit("file_artifact", {
                "path": f,
                "filename": os.path.basename(f),
                "session_id": ctx.session_id,
            })

    summary_parts = []
    if result["added"]:
        summary_parts.append(f"Added: {', '.join(result['added'])}")
    if result["modified"]:
        summary_parts.append(f"Modified: {', '.join(result['modified'])}")
    if result["deleted"]:
        summary_parts.append(f"Deleted: {', '.join(result['deleted'])}")

    return {
        "success": True,
        "summary": "; ".join(summary_parts),
        **result,
    }
