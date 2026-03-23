"""
TurnDiffTracker — 追踪单个 turn 内的文件变更。

在写入工具 (write_source_file / apply_patch) 执行前后捕获文件状态，
turn 结束时生成 unified diff，通过 EventBus 推送到前端。
"""

from __future__ import annotations

import difflib
import os


class TurnDiffTracker:
    """追踪单个 turn 内所有文件写入操作，生成累积 diff。"""

    def __init__(self, workspace: str) -> None:
        self._workspace = workspace
        self._baselines: dict[str, str | None] = {}  # abs_path → 原始内容 (None=不存在)
        self._writes: dict[str, str] = {}             # abs_path → operation

    def capture_baseline(self, abs_path: str) -> None:
        """懒捕获: 只在首次写入前读文件内容。多次调用只保留首次。"""
        if abs_path in self._baselines:
            return
        if os.path.isfile(abs_path):
            try:
                with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                    self._baselines[abs_path] = f.read()
            except OSError:
                self._baselines[abs_path] = None
        else:
            self._baselines[abs_path] = None

    def record_write(self, abs_path: str, operation: str) -> None:
        """记录写入操作 (create/modify/delete)。"""
        self._writes[abs_path] = operation

    def generate_diffs(self) -> list[dict]:
        """读当前文件 vs baseline，用 difflib.unified_diff 生成 diff。"""
        results = []
        for abs_path, operation in self._writes.items():
            before = self._baselines.get(abs_path)
            rel = os.path.relpath(abs_path, self._workspace)

            before_lines = before.splitlines(keepends=True) if before else []
            before_size = len(before) if before else 0

            if operation == "delete":
                after_lines: list[str] = []
                after_size = 0
            else:
                try:
                    with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                        after_content = f.read()
                    after_lines = after_content.splitlines(keepends=True)
                    after_size = len(after_content)
                except OSError:
                    after_lines = []
                    after_size = 0

            diff_lines = list(difflib.unified_diff(
                before_lines, after_lines,
                fromfile=f"a/{rel}", tofile=f"b/{rel}",
                lineterm="",
            ))
            diff_text = "\n".join(diff_lines)

            results.append({
                "path": rel,
                "operation": operation,
                "diff_text": diff_text,
                "before_size": before_size,
                "after_size": after_size,
            })

        return results

    def undo_all(self) -> list[dict]:
        """
        #20 Undo: 将所有已写入的文件恢复到 baseline 状态。

        Returns:
            list of {"path": rel, "restored": bool, "detail": str}
        """
        results = []
        for abs_path, operation in self._writes.items():
            rel = os.path.relpath(abs_path, self._workspace)
            baseline = self._baselines.get(abs_path)
            try:
                if baseline is None:
                    # 文件在写入前不存在 → 删除
                    if os.path.exists(abs_path):
                        os.remove(abs_path)
                        results.append({"path": rel, "restored": True, "detail": "deleted (was new)"})
                    else:
                        results.append({"path": rel, "restored": True, "detail": "already absent"})
                else:
                    # 恢复 baseline 内容
                    with open(abs_path, "w", encoding="utf-8") as f:
                        f.write(baseline)
                    results.append({"path": rel, "restored": True, "detail": "restored to baseline"})
            except OSError as e:
                results.append({"path": rel, "restored": False, "detail": str(e)})

        # 清除状态
        self._writes.clear()
        return results
