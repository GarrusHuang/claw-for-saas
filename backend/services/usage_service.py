"""
UsageService — 用量统计记录与查询。

记录每次 pipeline 执行的 token/tool/时长指标，
支持按租户/用户/日期维度的聚合查询和存储用量计算。
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class UsageService:
    """用量统计服务 — 复用 DatabaseService 的 SQLite 文件。"""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._data_dir = str(Path(db_path).parent)  # data/

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    # ── 写入 ──

    def record_pipeline(
        self,
        *,
        tenant_id: str,
        user_id: str,
        session_id: str,
        business_type: str = "general_chat",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        tool_call_count: int = 0,
        iterations: int = 0,
        duration_ms: float = 0.0,
        status: str = "success",
        model: str = "",
        tool_names: list[str] | None = None,
    ) -> int:
        """
        记录一次 pipeline 执行。

        在一个事务内同时 INSERT usage_events + UPSERT usage_daily。
        Returns: 新记录的 id
        """
        now = time.time()
        date_str = datetime.fromtimestamp(now).strftime("%Y-%m-%d")
        tool_names_json = json.dumps(tool_names or [])
        is_success = 1 if status == "success" else 0
        is_failed = 0 if status == "success" else 1

        conn = self._get_conn()
        try:
            cursor = conn.execute(
                """INSERT INTO usage_events
                   (tenant_id, user_id, session_id, business_type,
                    prompt_tokens, completion_tokens, total_tokens,
                    tool_call_count, iterations, duration_ms,
                    status, model, tool_names, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    tenant_id, user_id, session_id, business_type,
                    prompt_tokens, completion_tokens, total_tokens,
                    tool_call_count, iterations, duration_ms,
                    status, model, tool_names_json, now,
                ),
            )
            event_id = cursor.lastrowid

            conn.execute(
                """INSERT INTO usage_daily
                   (tenant_id, user_id, date,
                    total_requests, total_prompt_tokens, total_completion_tokens,
                    total_tokens, total_tool_calls, total_duration_ms,
                    success_count, failed_count)
                   VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(tenant_id, user_id, date) DO UPDATE SET
                    total_requests = total_requests + 1,
                    total_prompt_tokens = total_prompt_tokens + excluded.total_prompt_tokens,
                    total_completion_tokens = total_completion_tokens + excluded.total_completion_tokens,
                    total_tokens = total_tokens + excluded.total_tokens,
                    total_tool_calls = total_tool_calls + excluded.total_tool_calls,
                    total_duration_ms = total_duration_ms + excluded.total_duration_ms,
                    success_count = success_count + excluded.success_count,
                    failed_count = failed_count + excluded.failed_count""",
                (
                    tenant_id, user_id, date_str,
                    prompt_tokens, completion_tokens, total_tokens,
                    tool_call_count, duration_ms,
                    is_success, is_failed,
                ),
            )

            conn.commit()
            return event_id
        finally:
            conn.close()

    # ── 查询 — 管理员 ──

    def _date_to_ts(self, date_str: str | None, end_of_day: bool = False) -> float | None:
        """YYYY-MM-DD → Unix timestamp (start or end of day)."""
        if not date_str:
            return None
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            if end_of_day:
                return dt.timestamp() + 86400 - 0.001
            return dt.timestamp()
        except ValueError:
            return None

    def get_tenant_usage(
        self, tenant_id: str, start_date: str | None = None, end_date: str | None = None
    ) -> dict:
        """租户汇总统计。"""
        conn = self._get_conn()
        try:
            where = "WHERE tenant_id = ?"
            params: list = [tenant_id]
            ts_start = self._date_to_ts(start_date)
            ts_end = self._date_to_ts(end_date, end_of_day=True)
            if ts_start:
                where += " AND created_at >= ?"
                params.append(ts_start)
            if ts_end:
                where += " AND created_at <= ?"
                params.append(ts_end)

            row = conn.execute(
                f"""SELECT
                    COUNT(*) as total_requests,
                    COALESCE(SUM(prompt_tokens), 0) as total_prompt_tokens,
                    COALESCE(SUM(completion_tokens), 0) as total_completion_tokens,
                    COALESCE(SUM(total_tokens), 0) as total_tokens,
                    COALESCE(SUM(tool_call_count), 0) as total_tool_calls,
                    COALESCE(SUM(duration_ms), 0) as total_duration_ms,
                    COALESCE(SUM(CASE WHEN status='success' THEN 1 ELSE 0 END), 0) as success_count,
                    COALESCE(SUM(CASE WHEN status!='success' THEN 1 ELSE 0 END), 0) as failed_count
                FROM usage_events {where}""",
                params,
            ).fetchone()

            d = dict(row)
            d["avg_tokens_per_request"] = (
                round(d["total_tokens"] / d["total_requests"], 1)
                if d["total_requests"] > 0 else 0
            )
            d["avg_duration_ms"] = (
                round(d["total_duration_ms"] / d["total_requests"], 1)
                if d["total_requests"] > 0 else 0
            )
            return d
        finally:
            conn.close()

    def get_tenant_daily(
        self, tenant_id: str, start_date: str | None = None, end_date: str | None = None
    ) -> list[dict]:
        """租户日明细（从 usage_daily 预聚合表）。"""
        conn = self._get_conn()
        try:
            where = "WHERE tenant_id = ?"
            params: list = [tenant_id]
            if start_date:
                where += " AND date >= ?"
                params.append(start_date)
            if end_date:
                where += " AND date <= ?"
                params.append(end_date)

            rows = conn.execute(
                f"""SELECT date,
                    SUM(total_requests) as total_requests,
                    SUM(total_prompt_tokens) as total_prompt_tokens,
                    SUM(total_completion_tokens) as total_completion_tokens,
                    SUM(total_tokens) as total_tokens,
                    SUM(total_tool_calls) as total_tool_calls,
                    SUM(total_duration_ms) as total_duration_ms,
                    SUM(success_count) as success_count,
                    SUM(failed_count) as failed_count
                FROM usage_daily {where}
                GROUP BY date
                ORDER BY date DESC""",
                params,
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_tenant_user_ranking(
        self,
        tenant_id: str,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """用户排名（按 total_tokens 降序）。"""
        conn = self._get_conn()
        try:
            where = "WHERE tenant_id = ?"
            params: list = [tenant_id]
            if start_date:
                where += " AND date >= ?"
                params.append(start_date)
            if end_date:
                where += " AND date <= ?"
                params.append(end_date)

            rows = conn.execute(
                f"""SELECT user_id,
                    SUM(total_requests) as total_requests,
                    SUM(total_tokens) as total_tokens,
                    SUM(total_tool_calls) as total_tool_calls,
                    SUM(total_duration_ms) as total_duration_ms
                FROM usage_daily {where}
                GROUP BY user_id
                ORDER BY total_tokens DESC
                LIMIT ?""",
                params + [limit],
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_user_usage(
        self,
        tenant_id: str,
        user_id: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict:
        """单用户汇总统计。"""
        conn = self._get_conn()
        try:
            where = "WHERE tenant_id = ? AND user_id = ?"
            params: list = [tenant_id, user_id]
            ts_start = self._date_to_ts(start_date)
            ts_end = self._date_to_ts(end_date, end_of_day=True)
            if ts_start:
                where += " AND created_at >= ?"
                params.append(ts_start)
            if ts_end:
                where += " AND created_at <= ?"
                params.append(ts_end)

            row = conn.execute(
                f"""SELECT
                    COUNT(*) as total_requests,
                    COALESCE(SUM(prompt_tokens), 0) as total_prompt_tokens,
                    COALESCE(SUM(completion_tokens), 0) as total_completion_tokens,
                    COALESCE(SUM(total_tokens), 0) as total_tokens,
                    COALESCE(SUM(tool_call_count), 0) as total_tool_calls,
                    COALESCE(SUM(duration_ms), 0) as total_duration_ms,
                    COALESCE(SUM(CASE WHEN status='success' THEN 1 ELSE 0 END), 0) as success_count,
                    COALESCE(SUM(CASE WHEN status!='success' THEN 1 ELSE 0 END), 0) as failed_count
                FROM usage_events {where}""",
                params,
            ).fetchone()

            d = dict(row)
            d["avg_tokens_per_request"] = (
                round(d["total_tokens"] / d["total_requests"], 1)
                if d["total_requests"] > 0 else 0
            )
            d["avg_duration_ms"] = (
                round(d["total_duration_ms"] / d["total_requests"], 1)
                if d["total_requests"] > 0 else 0
            )
            return d
        finally:
            conn.close()

    def get_user_daily(
        self,
        tenant_id: str,
        user_id: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict]:
        """单用户日明细。"""
        conn = self._get_conn()
        try:
            where = "WHERE tenant_id = ? AND user_id = ?"
            params: list = [tenant_id, user_id]
            if start_date:
                where += " AND date >= ?"
                params.append(start_date)
            if end_date:
                where += " AND date <= ?"
                params.append(end_date)

            rows = conn.execute(
                f"""SELECT * FROM usage_daily {where}
                ORDER BY date DESC""",
                params,
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_recent_events(
        self,
        tenant_id: str,
        user_id: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """最近的原始事件列表。"""
        conn = self._get_conn()
        try:
            where = "WHERE tenant_id = ?"
            params: list = [tenant_id]
            if user_id:
                where += " AND user_id = ?"
                params.append(user_id)

            rows = conn.execute(
                f"""SELECT * FROM usage_events {where}
                ORDER BY created_at DESC
                LIMIT ?""",
                params + [limit],
            ).fetchall()
            results = []
            for r in rows:
                d = dict(r)
                d["tool_names"] = json.loads(d["tool_names"])
                results.append(d)
            return results
        finally:
            conn.close()

    def get_tool_usage_stats(
        self,
        tenant_id: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict]:
        """工具使用频率统计。"""
        conn = self._get_conn()
        try:
            where = "WHERE tenant_id = ?"
            params: list = [tenant_id]
            ts_start = self._date_to_ts(start_date)
            ts_end = self._date_to_ts(end_date, end_of_day=True)
            if ts_start:
                where += " AND created_at >= ?"
                params.append(ts_start)
            if ts_end:
                where += " AND created_at <= ?"
                params.append(ts_end)

            rows = conn.execute(
                f"SELECT tool_names FROM usage_events {where}",
                params,
            ).fetchall()

            # Python-side aggregation of JSON tool_names
            tool_counts: dict[str, int] = {}
            for r in rows:
                names = json.loads(r["tool_names"])
                for name in names:
                    tool_counts[name] = tool_counts.get(name, 0) + 1

            return sorted(
                [{"tool_name": k, "call_count": v} for k, v in tool_counts.items()],
                key=lambda x: x["call_count"],
                reverse=True,
            )
        finally:
            conn.close()

    def get_storage_usage(
        self, tenant_id: str, user_id: str | None = None
    ) -> dict:
        """
        存储用量计算 — 扫描文件系统。

        扫描目录:
        - data/sessions/{tenant_id}/
        - data/memory/tenant/{tenant_id}/
        - data/files/
        """
        def _dir_size(path: str) -> int:
            total = 0
            if not os.path.isdir(path):
                return 0
            for dirpath, _dirnames, filenames in os.walk(path):
                for f in filenames:
                    fp = os.path.join(dirpath, f)
                    try:
                        total += os.path.getsize(fp)
                    except OSError:
                        pass
            return total

        sessions_path = os.path.join(self._data_dir, "sessions", tenant_id)
        memory_path = os.path.join(self._data_dir, "memory", "tenant", tenant_id)
        files_path = os.path.join(self._data_dir, "files")

        if user_id:
            sessions_path = os.path.join(sessions_path, user_id)
            memory_path = os.path.join(self._data_dir, "memory", "user", tenant_id, user_id)
            files_path = os.path.join(files_path, user_id)

        sessions_bytes = _dir_size(sessions_path)
        memory_bytes = _dir_size(memory_path)
        files_bytes = _dir_size(files_path)

        return {
            "sessions_bytes": sessions_bytes,
            "memory_bytes": memory_bytes,
            "files_bytes": files_bytes,
            "total_bytes": sessions_bytes + memory_bytes + files_bytes,
        }
