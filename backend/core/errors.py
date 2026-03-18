"""
错误分类系统 — Phase 8。

提供统一的错误分类和结构化异常，
使得 Runtime/Gateway/API 可以区分可恢复/不可恢复错误，
并做出正确的重试/降级决策。

Usage:
    from core.errors import AgentError, ErrorCategory, classify_error

    # 主动抛出
    raise AgentError("限流", category=ErrorCategory.RATE_LIMIT, recoverable=True)

    # 从状态码推断
    cat = classify_error(status_code=429)
"""

from __future__ import annotations

import asyncio
import re
from enum import Enum


class ErrorCategory(str, Enum):
    """错误类别枚举"""
    RATE_LIMIT = "rate_limit"              # 429, 限流
    OVERLOADED = "overloaded"              # 503, 服务过载
    CONTEXT_OVERFLOW = "context_overflow"  # 上下文超限
    AUTH = "auth"                          # 401/403, 认证失败
    TOOL_ERROR = "tool_error"              # 工具执行失败
    TOOL_TIMEOUT = "tool_timeout"          # 工具超时
    LLM_ERROR = "llm_error"               # LLM 返回错误
    NETWORK = "network"                    # 网络连接失败
    INTERNAL = "internal"                  # 内部错误
    VALIDATION = "validation"              # 输入验证失败
    MODEL_UNAVAILABLE = "model_unavailable"  # 模型不可用 (需降级)
    BILLING = "billing"                    # 计费错误


# 哪些错误类型可自动恢复
_RECOVERABLE_CATEGORIES = {
    ErrorCategory.RATE_LIMIT,
    ErrorCategory.OVERLOADED,
    ErrorCategory.NETWORK,
    ErrorCategory.CONTEXT_OVERFLOW,
    ErrorCategory.TOOL_TIMEOUT,
}

# 建议操作映射
_SUGGESTED_ACTIONS = {
    ErrorCategory.RATE_LIMIT: "请等待片刻后重试",
    ErrorCategory.OVERLOADED: "服务繁忙，请稍后再试",
    ErrorCategory.CONTEXT_OVERFLOW: "对话过长，已自动压缩上下文，请重试",
    ErrorCategory.AUTH: "认证失败，请检查 API Key 配置",
    ErrorCategory.TOOL_ERROR: "工具执行出错，Agent 将尝试其他方式",
    ErrorCategory.TOOL_TIMEOUT: "工具调用超时，请重试",
    ErrorCategory.LLM_ERROR: "AI 模型返回错误，请重试",
    ErrorCategory.NETWORK: "网络连接失败，请检查连接后重试",
    ErrorCategory.INTERNAL: "内部错误，请联系管理员",
    ErrorCategory.VALIDATION: "请求参数错误，请检查输入",
    ErrorCategory.MODEL_UNAVAILABLE: "当前模型不可用，正在切换备用模型",
    ErrorCategory.BILLING: "计费错误，请检查账户状态",
}


class AgentError(Exception):
    """带分类的 Agent 异常"""

    def __init__(
        self,
        message: str,
        category: ErrorCategory = ErrorCategory.INTERNAL,
        recoverable: bool | None = None,
        retry_after_s: float | None = None,
        details: dict | None = None,
        affected_step: str = "",
    ) -> None:
        super().__init__(message)
        self.category = category
        self.recoverable = (
            recoverable if recoverable is not None
            else category in _RECOVERABLE_CATEGORIES
        )
        self.retry_after_s = retry_after_s
        self.details = details or {}
        self.affected_step = affected_step

    @property
    def suggested_action(self) -> str:
        return _SUGGESTED_ACTIONS.get(self.category, "请重试")

    def to_error_event(self, trace_id: str = "") -> dict:
        """转换为 ErrorEvent payload dict"""
        return {
            "code": self.category.value.upper(),
            "message": str(self),
            "recoverable": self.recoverable,
            "category": self.category.value,
            "affected_step": self.affected_step,
            "suggested_action": self.suggested_action,
            "trace_id": trace_id,
        }


def classify_error(
    status_code: int = 0,
    error_msg: str = "",
    exception: Exception | None = None,
) -> ErrorCategory:
    """
    从状态码/错误信息/异常类型推断错误类别。

    Args:
        status_code: HTTP 状态码
        error_msg: 错误消息文本
        exception: 原始异常对象

    Returns:
        ErrorCategory
    """
    # 从异常类型推断
    if exception is not None:
        import httpx
        if isinstance(exception, (httpx.ConnectError, httpx.ConnectTimeout)):
            return ErrorCategory.NETWORK
        if isinstance(exception, httpx.TimeoutException):
            return ErrorCategory.NETWORK
        if isinstance(exception, asyncio.TimeoutError):
            return ErrorCategory.TOOL_TIMEOUT

    # 从状态码推断
    if status_code == 429:
        return ErrorCategory.RATE_LIMIT
    if status_code in (401, 403):
        return ErrorCategory.AUTH
    if status_code == 503:
        return ErrorCategory.OVERLOADED
    if status_code in (500, 502):
        return ErrorCategory.LLM_ERROR
    if 400 <= status_code < 500:
        return ErrorCategory.VALIDATION

    # 从错误消息推断
    msg_lower = error_msg.lower()
    context_overflow_keywords = [
        "context_length", "context length", "token limit",
        "maximum context", "too many tokens", "上下文超限",
        "max_tokens", "context window",
    ]
    if any(kw in msg_lower for kw in context_overflow_keywords):
        return ErrorCategory.CONTEXT_OVERFLOW

    rate_limit_keywords = ["rate limit", "too many requests", "限流", "throttl"]
    if any(kw in msg_lower for kw in rate_limit_keywords):
        return ErrorCategory.RATE_LIMIT

    network_keywords = ["connection", "connect", "timeout", "网络"]
    if any(kw in msg_lower for kw in network_keywords):
        return ErrorCategory.NETWORK

    model_unavailable_keywords = ["model not found", "model_not_found", "no such model",
                                   "model is currently overloaded", "decommissioned"]
    if any(kw in msg_lower for kw in model_unavailable_keywords):
        return ErrorCategory.MODEL_UNAVAILABLE

    billing_keywords = ["billing", "quota exceeded", "insufficient_quota", "payment"]
    if any(kw in msg_lower for kw in billing_keywords):
        return ErrorCategory.BILLING

    return ErrorCategory.INTERNAL
