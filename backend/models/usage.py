"""
用量统计 Pydantic 响应模型 (A10)。
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class UsageSummary(BaseModel):
    """汇总统计。"""
    total_requests: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    total_tool_calls: int = 0
    total_duration_ms: float = 0.0
    success_count: int = 0
    failed_count: int = 0
    avg_tokens_per_request: float = 0.0
    avg_duration_ms: float = 0.0


class DailyUsage(BaseModel):
    """日明细行。"""
    date: str
    total_requests: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    total_tool_calls: int = 0
    total_duration_ms: float = 0.0
    success_count: int = 0
    failed_count: int = 0


class UserRanking(BaseModel):
    """用户排名行。"""
    user_id: str
    total_requests: int = 0
    total_tokens: int = 0
    total_tool_calls: int = 0
    total_duration_ms: float = 0.0


class ToolUsageStat(BaseModel):
    """工具调用频率。"""
    tool_name: str
    call_count: int = 0


class UsageEvent(BaseModel):
    """原始事件记录。"""
    id: int
    tenant_id: str
    user_id: str
    session_id: str
    business_type: str = "general_chat"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    tool_call_count: int = 0
    iterations: int = 0
    duration_ms: float = 0.0
    status: str = "success"
    model: str = ""
    tool_names: list[str] = Field(default_factory=list)
    created_at: float = 0.0


class StorageUsage(BaseModel):
    """存储用量。"""
    sessions_bytes: int = 0
    memory_bytes: int = 0
    files_bytes: int = 0
    total_bytes: int = 0
