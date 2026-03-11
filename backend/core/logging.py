"""
结构化日志配置。

使用 structlog 实现：
- trace_id 贯穿整个 Pipeline 执行
- 每个工具调用、LLM 调用、状态变更都有日志
- 支持 console（开发）和 JSON（生产）两种格式
"""

from __future__ import annotations

import logging
import sys

import structlog


def setup_logging(level: str = "INFO", format: str = "console") -> None:
    """
    配置结构化日志。

    Args:
        level: 日志级别 (DEBUG, INFO, WARNING, ERROR)
        format: 输出格式 ("console" 开发模式, "json" 生产模式)
    """
    # 配置标准 logging
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        stream=sys.stdout,
        format="%(message)s",
    )

    # 选择渲染器
    if format == "json":
        renderer = structlog.processors.JSONRenderer(ensure_ascii=False)
    else:
        renderer = structlog.dev.ConsoleRenderer(
            colors=True,
            exception_formatter=structlog.dev.plain_traceback,
        )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.UnicodeDecoder(),
            renderer,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = __name__, **kwargs) -> structlog.stdlib.BoundLogger:
    """
    获取带绑定上下文的 logger。

    Usage:
        logger = get_logger("runtime", trace_id="abc123", agent="universal_audit")
        logger.info("tool_executed", tool="calculator", result={"pass": True})
    """
    return structlog.get_logger(name, **kwargs)
