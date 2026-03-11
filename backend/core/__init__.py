"""
Agent Harness 核心层。

从 agent-engine 项目借鉴的关键设计模式：
- AgenticRuntime: ReAct 风格 LLM+Tool 迭代循环
- ToolRegistry: 装饰器注册 + 类型提示自动 schema 提取
- ToolCallParser: 双模式工具调用解析（原生 OpenAI + Hermes XML 回退）
- LLMGatewayClient: 异步 LLM 客户端（retry、streaming、token 追踪）
- EventBus: 解耦 SSE 事件发射
"""

from .runtime import AgenticRuntime, RuntimeConfig, RuntimeResult
from .tool_registry import ToolRegistry, ToolResult
from .tool_protocol import ToolCallParser
from .llm_client import LLMGatewayClient, LLMClientConfig
from .event_bus import EventBus

__all__ = [
    "AgenticRuntime",
    "RuntimeConfig",
    "RuntimeResult",
    "ToolRegistry",
    "ToolResult",
    "ToolCallParser",
    "LLMGatewayClient",
    "LLMClientConfig",
    "EventBus",
]
